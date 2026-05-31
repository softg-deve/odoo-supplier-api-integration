# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request, Response
import logging

_logger = logging.getLogger(__name__)


class CSVViewerController(http.Controller):
    """
    CSV Viewer - Always synchronized with the API
    """
    
    @http.route('/csv/view/<int:category_id>', 
                type='http', 
                auth='user',
                website=True,
                csrf=False)
    def view_csv_live(self, category_id, **kwargs):
        """
        Display CSV in real-time from the API

        URL: /csv/view/42
        """
        
        try:
            category = request.env['supplier.api.category'].sudo().browse(category_id)
            
            if not category.exists():
                return request.render('website.404')
            
            supplier = category.supplier_id
            
            _logger.info(f"Loading CSV for: {category.complete_name}")
            
            result = supplier._tme_api_call('/Products/GetSymbols', {
                'CategoryId': category.external_id
            })
            
            symbol_list = result.get('Data', {}).get('SymbolList', [])
            
            if not symbol_list:
                return self._render_empty(category)
            
            max_products = min(len(symbol_list), 500)
            
            _logger.info(f"Fetching {max_products} products...")
            
            all_products = []
            for i in range(0, max_products, 50):
                batch = symbol_list[i:i+50]
                try:
                    products_data = supplier._fetch_product_details_batch(batch)
                    all_products.extend(products_data)
                except Exception as e:
                    _logger.error(f"Batch error: {str(e)}")
                    continue
            
            if not all_products:
                return self._render_empty(category)
            
            Product = request.env['product.template'].sudo()
            
            products_with_status = []
            for product in all_products:
                symbol = product.get('symbol')
                barcode = product.get('barcode')
                
                exists = Product.search_count([
                    '|',
                    ('barcode', '=', barcode),
                    ('api_external_id', '=', symbol)
                ]) > 0
                
                cost = product.get('price', 0.0)
                sale = (cost * 1.3) if category.show_sale_price else 0.0
                
                products_with_status.append({
                    'symbol': symbol or '',
                    'name': product.get('name', symbol),
                    'manufacturer': product.get('manufacturer', ''),
                    'barcode': barcode or '',
                    'stock': product.get('stock', 0),
                    'cost': f"{cost:.2f}",
                    'sale': f"{sale:.2f}",
                    'currency': product.get('currency', supplier.currency),
                    'weight': f"{product.get('weight', 0.0):.3f}",
                    'photo': product.get('photo', ''),
                    'exists': exists,
                })
            
            _logger.info(f"Loaded {len(products_with_status)} products successfully")
            
            return request.render('supplier_api_integration.csv_viewer_live', {
                'category': category,
                'supplier': supplier,
                'products': products_with_status,
                'total_count': len(products_with_status),
                'exists_count': sum(1 for p in products_with_status if p['exists']),
                'new_count': sum(1 for p in products_with_status if not p['exists']),
                'total_available': len(symbol_list),
            })
            
        except Exception as e:
            _logger.error(f"CSV Viewer error: {str(e)}", exc_info=True)
            return Response(f'Error: {str(e)}', status=500)
    
    
    def _render_empty(self, category):
        """Render empty page when no products found"""
        return request.render('supplier_api_integration.csv_viewer_empty', {
            'category': category,
            'supplier': category.supplier_id,
        })