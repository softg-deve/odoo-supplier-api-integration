# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    supplier_api_id = fields.Many2one('supplier.api.config', 'Supplier API', ondelete='set null')
    supplier_api_category_id = fields.Many2one('supplier.api.category', 'API Category', ondelete='set null')
    api_external_id = fields.Char('API External ID', index=True)
    api_last_sync = fields.Datetime('Last API Sync', readonly=True)
    image_url = fields.Char('Image URL', readonly=True)

    supplier_stock_qty = fields.Integer(
        string='Supplier Stock',
        default=0,
    )
    supplier_id = fields.Selection([
        ('other', 'Other'),
        ('tme', 'TME Electronics'),
    ], string='Supplier', default='other', help='Select the supplier for this product')

    def _ensure_supplier_info(self):
        """Automatically create a product.supplierinfo if missing"""
        self.ensure_one()

        if not self.supplier_api_id:
            return

        partner = self.supplier_api_id._get_or_create_supplier_partner()
        if not partner:
            _logger.warning(f"No supplier partner found for {self.supplier_api_id.name}")
            return

        existing = self.env['product.supplierinfo'].search([
            ('product_tmpl_id', '=', self.id),
            ('partner_id', '=', partner.id)
        ], limit=1)

        if not existing:
            self.env['product.supplierinfo'].sudo().create({
                'product_tmpl_id': self.id,
                'partner_id': partner.id,
                'price': self.standard_price or 0,
                'min_qty': 1,
                'api_stock_quantity': self.supplier_stock_qty or 0,
                'delay': 1,
            })
            _logger.info(f"Created supplier_info for {self.name} with {partner.name}")
        else:
            if existing.api_stock_quantity != self.supplier_stock_qty:
                existing.sudo().write({
                    'api_stock_quantity': self.supplier_stock_qty or 0,
                })
                _logger.info(f"Updated supplier_info stock for {self.name}: {self.supplier_stock_qty}")

    def _get_supplier_location(self):
        """Get the Supplier Warehouse stock location"""
        location_id = self.env['ir.config_parameter'].sudo().get_param(
            'config_supplier_csv_cronjob.stock_supplier_id')

        if location_id:
            location = self.env['stock.location'].browse(int(location_id))
            if location.exists():
                return location

        location = self.env['stock.location'].search([
            ('name', '=', 'Supplier Warehouse'),
            ('usage', '=', 'internal')
        ], limit=1)

        if not location:
            warehouse = self.env['stock.warehouse'].search([], limit=1)
            if warehouse:
                location = self.env['stock.location'].sudo().create({
                    'name': 'Supplier Warehouse',
                    'usage': 'internal',
                    'location_id': warehouse.lot_stock_id.id,
                })

                self.env['ir.config_parameter'].sudo().set_param(
                    'supplier_api_integration.stock_supplier_id',
                    location.id
                )

                _logger.info(f"Created Supplier Warehouse: {location.complete_name}")

        return location

    def _get_supplier_quant_qty(self):
        """
        Read supplier quant quantity WITHOUT any modification.
        Returns the quantity in the Supplier Warehouse.
        """
        self.ensure_one()

        supplier_location = self._get_supplier_location()
        if not supplier_location:
            return 0

        variant = self.product_variant_ids[:1]
        if not variant:
            return 0

        quant = self.env['stock.quant'].sudo().search([
            ('product_id', '=', variant.id),
            ('location_id', '=', supplier_location.id)
        ], limit=1)

        return quant.quantity if quant else 0

    def _get_total_available_stock(self):
        self.ensure_one()

        if self.supplier_api_id:
            on_hand = self.qty_available if self.qty_available > 0 else 0
            supplier = self.supplier_stock_qty if self.supplier_stock_qty > 0 else 0
            return on_hand + supplier
        else:
            return self.qty_available

    def _get_stock_breakdown(self):
        self.ensure_one()

        if self.supplier_api_id:
            on_hand = self.qty_available if self.qty_available > 0 else 0
            supplier = self.supplier_stock_qty if self.supplier_stock_qty > 0 else 0

            variant = self.product_variant_ids[:1]
            available = variant.free_qty if variant else on_hand
            forecasted = variant.virtual_available if variant else on_hand

            return {
                'on_hand': on_hand,
                'supplier': supplier,
                'total': on_hand + supplier,
                'available': available,
                'forecasted': forecasted,
                'is_api': True
            }
        else:
            qty = self.qty_available if self.qty_available > 0 else 0
            variant = self.product_variant_ids[:1]

            return {
                'on_hand': qty,
                'supplier': 0,
                'total': qty,
                'available': variant.free_qty if variant else qty,
                'forecasted': variant.virtual_available if variant else qty,
                'is_api': False
            }

    def _setup_website_integration(self):
        self.ensure_one()

        if not self.env['ir.module.module'].search([
            ('name', '=', 'website_sale'),
            ('state', '=', 'installed')
        ]):
            return

        try:
            update_vals = {}

            if not self.sale_ok:
                update_vals['sale_ok'] = True

            if self.supplier_api_category_id:
                public_category = self.supplier_api_category_id._get_or_create_public_category()
                if public_category and public_category.id not in self.public_categ_ids.ids:
                    update_vals['public_categ_ids'] = [(4, public_category.id)]

            Product = self.env['product.template']

            if 'continue_seling' in Product._fields and not self.continue_seling:
                update_vals['continue_seling'] = True

            if 'showDelivryMessage' in Product._fields and not self.showDelivryMessage:
                update_vals['showDelivryMessage'] = True

            if 'show_availability' in Product._fields:
                update_vals['show_availability'] = True

            if 'messageDelivryTimeStock' in Product._fields and not self.messageDelivryTimeStock:
                update_vals['messageDelivryTimeStock'] = 'Ship 1-2 Days'

            if 'messageDelivryTimeRemoteStock' in Product._fields and not self.messageDelivryTimeRemoteStock:
                update_vals['messageDelivryTimeRemoteStock'] = 'Ship 4-8 Days'

            if 'out_of_stock_message' in Product._fields and not self.out_of_stock_message:
                update_vals['out_of_stock_message'] = 'Ask for Availability'

            total_stock = self._get_total_available_stock()

            if total_stock > 0:
                update_vals['is_published'] = True
                update_vals['website_published'] = True
            else:
                if 'continue_seling' in Product._fields and self.continue_seling:
                    update_vals['is_published'] = True
                    update_vals['website_published'] = True
                else:
                    update_vals['is_published'] = False
                    update_vals['website_published'] = False

            if update_vals:
                self.sudo().write(update_vals)

        except Exception as e:
            _logger.warning(f"Website setup error: {str(e)}")

    def action_sync_from_api(self):
        self.ensure_one()

        if not self.supplier_api_id or not self.api_external_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': 'No API configuration found',
                    'type': 'warning',
                }
            }

        try:
            supplier = self.supplier_api_id

            params = {f'SymbolList[00]': self.api_external_id}
            result = supplier._tme_api_call('/Products/GetProducts', params)

            if result.get('Status') != 'OK':
                raise Exception('API call failed')

            products_data = result.get('Data', {}).get('ProductList', [])
            if not products_data:
                raise Exception('Product not found')

            params_price = params.copy()
            params_price['Currency'] = supplier.currency
            prices_result = supplier._tme_api_call('/Products/GetPricesAndStocks', params_price)

            price_data = prices_result.get('Data', {}).get('ProductList', [{}])[0]
            price_list = price_data.get('PriceList', [])
            price = price_list[0].get('PriceValue', 0.0) if price_list else 0.0
            stock = price_data.get('Amount', 0)

            update_vals = {
                'standard_price': price,
                'api_last_sync': fields.Datetime.now(),
            }

            if self.supplier_api_category_id.show_sale_price:
                if self.list_price == 0 or self.list_price < price:
                    update_vals['list_price'] = price * 1.3

            partner = supplier._get_or_create_supplier_partner()
            supplier_info = self.env['product.supplierinfo'].search([
                ('product_tmpl_id', '=', self.id),
                ('partner_id', '=', partner.id)
            ], limit=1)

            if supplier_info:
                supplier_info.write({
                    'api_stock_quantity': stock,
                    'price': price,
                })

            self.write(update_vals)
            self._update_supplier_warehouse_qty(stock)
            self._setup_website_integration()

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Success!',
                    'message': f'Synced! Stock: {stock} units',
                    'type': 'success',
                }
            }

        except Exception as e:
            _logger.error(f"Sync error: {str(e)}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': f'Sync failed: {str(e)}',
                    'type': 'danger',
                }
            }

    def _sync_stock_to_product(self, product, wizard_stock_qty):
        self.ensure_one()

        try:
            partner = self.supplier_id._get_or_create_supplier_partner()

            supplier_info = self.env['product.supplierinfo'].search([
                ('product_tmpl_id', '=', product.id),
                ('partner_id', '=', partner.id)
            ], limit=1)

            if supplier_info:
                supplier_info.sudo().write({
                    'api_stock_quantity': wizard_stock_qty
                })
            else:
                self.env['product.supplierinfo'].sudo().create({
                    'product_tmpl_id': product.id,
                    'partner_id': partner.id,
                    'price': product.standard_price or 0,
                    'min_qty': 1,
                    'api_stock_quantity': wizard_stock_qty,
                })

            product.sudo().write({'supplier_stock_qty': wizard_stock_qty})
            product._sync_supplier_quants()
            _logger.info(f"  Stock sync: {product.default_code} = {wizard_stock_qty}")

        except Exception as e:
            _logger.error(f"  Stock sync error: {str(e)}")

    def action_open_quants_own(self):
        """
        Open On Hand quants EXCLUDING the Supplier Warehouse location.
        Replaces the native Odoo action_open_quants to filter out
        the Supplier Warehouse stock location.
        """
        self.ensure_one()

        supplier_location = self._get_supplier_location()

        domain = [
            ('product_id', 'in', self.product_variant_ids.ids),
            ('location_id.usage', '=', 'internal'),
        ]

        if supplier_location:
            domain.append(('location_id', '!=', supplier_location.id))

        return {
            'name': _('On Hand: %s') % self.name,
            'view_mode': 'list',
            'res_model': 'stock.quant',
            'type': 'ir.actions.act_window',
            'domain': domain,
            'context': {
                'default_product_id': self.product_variant_ids[:1].id,
                'search_default_internal_loc': 1,
            },
        }

    def _update_supplier_warehouse_qty(self, new_qty):
        """Centralized update of supplier warehouse stock quants"""
        self.ensure_one()

        location_id = self.env['ir.config_parameter'].sudo().get_param(
            'config_supplier_csv_cronjob.stock_supplier_id'
        )

        if not location_id:
            return False

        variant = self.product_variant_ids[:1]
        if not variant:
            return False

        qtyStock = self.env['stock.quant'].sudo().search([
            ('location_id', '=', int(location_id)),
            ('product_id', '=', variant.id),
        ], limit=1)

        if qtyStock:
            qtyStock.sudo().write({'inventory_quantity': new_qty})
        else:
            qtyStock = self.env['stock.quant'].sudo().create({
                'location_id': int(location_id),
                'product_id': variant.id,
                'inventory_quantity': new_qty
            })

        qtyStock.sudo().action_apply_inventory()
        self.sudo().write({'supplier_stock_qty': new_qty})
        return True

    def unlink(self):
        """
        After deleting a TME product, invalidate the synced_products
        smart button cache to force a recalculation.
        """
        suppliers = self.filtered(
            lambda p: p.supplier_id == 'tme'
        ).mapped('supplier_api_id')

        result = super(ProductTemplate, self).unlink()

        if suppliers:
            suppliers.invalidate_cache(['synced_products', 'products_without_category'])

        return result

    
    def _sync_public_category(self, new_api_category, old_api_category=None):
       
        self.ensure_one()

        if not new_api_category:
            return False

       
        new_pub_cat = new_api_category.public_category_id
        if not new_pub_cat:
            try:
                new_pub_cat = new_api_category._get_or_create_public_category()
            except Exception as e:
                _logger.error(
                    f"  {self.default_code}: _get_or_create_public_category "
                    f"failed for '{new_api_category.complete_name}': {str(e)}"
                )
                return False

        if not new_pub_cat:
            _logger.warning(
                f"  {self.default_code}: public_category_id vide sur "
                f"'{new_api_category.complete_name}', sync ignorée"
            )
            return False

        
        current_ids = list(self.public_categ_ids.ids)

      
        if old_api_category and old_api_category.id != new_api_category.id:
            old_pub_cat = old_api_category.public_category_id
            changed = False

           
            if old_pub_cat and old_pub_cat.id in current_ids:
                current_ids.remove(old_pub_cat.id)
                changed = True

          
            if new_pub_cat.id not in current_ids:
                current_ids.append(new_pub_cat.id)
                changed = True

            if changed:
                self.sudo().write({'public_categ_ids': [(6, 0, current_ids)]})
                _logger.info(
                    f"  {self.default_code}: [CAS 2] déplacé "
                    f"'{old_pub_cat.complete_name if old_pub_cat else '?'}' "
                    f"-> '{new_pub_cat.complete_name}'"
                )
                return True
            return False

      
        elif not current_ids:
            self.sudo().write({'public_categ_ids': [(6, 0, [new_pub_cat.id])]})
            _logger.info(
                f"  {self.default_code}: [CAS 1] set "
                f"'{new_pub_cat.complete_name}'"
            )
            return True

       
        else:
            if new_pub_cat.id not in current_ids:
                self.sudo().write({'public_categ_ids': [(4, new_pub_cat.id)]})
                _logger.info(
                    f"  {self.default_code}: [CAS 3] ajouté "
                    f"'{new_pub_cat.complete_name}' "
                    f"(total: {len(current_ids) + 1} catégories)"
                )
                return True
           
            return False


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _get_stock_breakdown(self):
        self.ensure_one()
        return self.product_tmpl_id._get_stock_breakdown()


# class ProductSupplierinfo(models.Model):
#     _inherit = 'product.supplierinfo'

#     api_stock_quantity = fields.Integer(
#         string='API Stock Quantity',
#         default=0,
#         help='Stock quantity from supplier API'
#     )

#     def write(self, vals):
#         result = super(ProductSupplierinfo, self).write(vals)

#         if 'api_stock_quantity' in vals:
#             for record in self:
#                 if record.product_tmpl_id:
#                     if record.product_tmpl_id.supplier_api_id:
#                         new_qty = vals['api_stock_quantity']
#                         record.product_tmpl_id._update_supplier_warehouse_qty(new_qty)
#                         _logger.info(
#                             f"Supplier stock updated: "
#                             f"{record.product_tmpl_id.default_code} = {new_qty} units"
#                         )
#         return result

#     @api.model
#     def create(self, vals):
#         record = super(ProductSupplierinfo, self).create(vals)

#         if 'api_stock_quantity' in vals and record.product_tmpl_id:
#             if record.product_tmpl_id.supplier_api_id:
#                 new_qty = vals['api_stock_quantity']
#                 record.product_tmpl_id._update_supplier_warehouse_qty(new_qty)
#                 _logger.info(
#                     f"Supplier stock created: "
#                     f"{record.product_tmpl_id.default_code} = {new_qty} units"
#                 )
#         return record

class ProductSupplierinfo(models.Model):
    _inherit = 'product.supplierinfo'

    api_stock_quantity = fields.Integer(
        string='API Stock Quantity',
        default=0,
        help='Stock quantity from supplier API'
    )