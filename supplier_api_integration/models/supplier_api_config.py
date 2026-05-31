# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import requests
import logging
import hmac
import hashlib
from urllib.parse import quote
import base64
import time
from PIL import Image
from io import BytesIO

_logger = logging.getLogger(__name__)


class SupplierApiConfig(models.Model):
    _name = 'supplier.api.config'
    _description = 'Supplier API Configuration'
    _order = 'sequence, name'

    name = fields.Char('Supplier Name', required=True)
    api_type = fields.Selection([
        ('tme', 'TME API'),
    ], string='API Type', required=True, default='tme')

    api_key = fields.Char('API Token', required=True)
    api_secret = fields.Char('App Secret', required=True, password=True)
    api_url = fields.Char('API URL', default='https://api.tme.eu', required=True)

    country = fields.Char('Country Code', default='GB')
    language = fields.Char('Language Code', default='EN')
    currency = fields.Char('Currency Code', default='EUR')

    active = fields.Boolean('Active', default=True)
    sequence = fields.Integer('Sequence', default=10)

    auto_sync = fields.Boolean('Auto Synchronization', default=True)

    last_sync_date = fields.Datetime('Last Synchronization', readonly=True)
    category_ids = fields.One2many('supplier.api.category', 'supplier_id', string='Categories')
    synced_products = fields.Integer('Synced Products', compute='_compute_stats')
    products_without_category = fields.Integer('Without Category', compute='_compute_stats')

    show_sale_price = fields.Boolean(
        'Show Sale Price in Products',
        default=True,
        help="If enabled, products imported from this API will display sale prices."
    )

    # def _compute_stats(self):
    #     for rec in self:
    #         # rec.synced_products = self.env['product.template'].search_count([
    #         #     ('supplier_id', '=', rec.api_type),
    #         # ])
    #         # rec.products_without_category = self.env['product.template'].search_count([
    #         #     ('supplier_id', '=', rec.api_type),
    #         #     ('supplier_api_category_id', '=', False),
    #         # ])
    #         # ✅ CORRECT — doit compter par supplier_api_id (Many2one vers ce record précis)
    #         rec.synced_products = self.env['product.template'].search_count([
    #             ('supplier_api_id', '=', rec.id),
    #         ])
    #         rec.products_without_category = self.env['product.template'].search_count([
    #             ('supplier_api_id', '=', rec.id),
    #             ('supplier_api_category_id', '=', False),
    #         ])
    def _compute_stats(self):
        for rec in self:
            rec.synced_products = self.env['product.template'].search_count([
                ('supplier_api_id', '=', rec.id),
            ])
            rec.products_without_category = self.env['product.template'].search_count([
                ('supplier_api_id', '=', rec.id),
                ('supplier_api_category_id', '=', False),
            ])

    def action_view_products_without_category(self):
        """Display products WITHOUT a category"""
        self.ensure_one()
        return {
            'name': _('Products Without Category: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'product.template',
            'view_mode': 'tree,form',
            # 'domain': [
            #     ('supplier_id', '=', self.api_type),
            #     ('supplier_api_category_id', '=', False),
            # ],
            # ✅ CORRECT
            'domain': [
                ('supplier_api_id', '=', self.id),
                ('supplier_api_category_id', '=', False),
            ],
            'context': {
                'default_supplier_api_id': self.id,
            },
        }

    def _url_encode(self, value):
        if isinstance(value, (list, tuple)):
            value = str(value)
        return quote(str(value), safe='')

    def _generate_tme_signature(self, endpoint, params):
        base_url = self.api_url.rstrip('/')
        if not endpoint.endswith('.json'):
            endpoint = f"{endpoint}.json"

        full_url = f"{base_url}{endpoint}"
        params_for_signature = {k: v for k, v in params.items() if k != 'ApiSignature'}
        sorted_params = sorted(params_for_signature.items())

        encoded_params = [f"{self._url_encode(k)}={self._url_encode(v)}" for k, v in sorted_params]
        params_string = '&'.join(encoded_params)
        signature_base = f"POST&{self._url_encode(full_url)}&{self._url_encode(params_string)}"

        signature_bytes = hmac.new(
            self.api_secret.encode('utf-8'),
            msg=signature_base.encode('utf-8'),
            digestmod=hashlib.sha1
        ).digest()

        return base64.b64encode(signature_bytes).decode('utf-8')

    def _tme_api_call(self, endpoint, params=None):
        if params is None:
            params = {}

        base_url = self.api_url.rstrip('/')
        if not endpoint.endswith('.json'):
            endpoint = f"{endpoint}.json"

        url = f"{base_url}{endpoint}"

        request_params = {
            'Token': self.api_key,
            'Language': self.language or 'EN',
            'Country': self.country or 'GB',
        }

        if 'Currency' in params:
            request_params['Currency'] = params.pop('Currency')
        elif self.currency:
            request_params['Currency'] = self.currency

        request_params.update(params)
        signature = self._generate_tme_signature(endpoint, request_params)
        request_params['ApiSignature'] = signature

        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

            response = requests.post(url, data=request_params, timeout=60, verify=False)
            response.raise_for_status()
            data = response.json()

            if data.get('Status') != 'OK':
                error_msg = data.get('Message', 'Unknown error')
                raise UserError(_('TME API Error: %s') % error_msg)

            return data

        except requests.exceptions.RequestException as e:
            _logger.error(f"TME API Error: {str(e)}")
            raise UserError(_('Connection Error: %s') % str(e))

    def _fix_photo_url(self, photo_url):
        """Fix and normalize photo URLs"""
        if not photo_url:
            return ''

        if photo_url.startswith('//'):
            photo_url = f"https:{photo_url}"
        elif not photo_url.startswith('http'):
            photo_url = f"https://{photo_url}"

        return photo_url

    def _fetch_product_details_batch(self, symbol_list):
        """Fetch product details for a batch of symbols"""
        if not symbol_list:
            return []

        params = {}
        for i, symbol in enumerate(symbol_list):
            params[f'SymbolList[{i:02d}]'] = symbol

        products_result = self._tme_api_call('/Products/GetProducts', params)
        params_price = params.copy()
        params_price['Currency'] = self.currency
        prices_result = self._tme_api_call('/Products/GetPricesAndStocks', params_price)

        products_data = products_result.get('Data', {}).get('ProductList', [])
        prices_data = prices_result.get('Data', {}).get('ProductList', [])
        prices_dict = {p.get('Symbol'): p for p in prices_data}

        result = []
        for product_data in products_data:
            symbol = product_data.get('Symbol')
            price_data = prices_dict.get(symbol, {})
            price_list = price_data.get('PriceList', [])
            price = price_list[0].get('PriceValue', 0.0) if price_list else 0.0

            weight_raw = product_data.get('Weight', '')
            weight_kg = self._parse_weight_to_kg(weight_raw)

            photo_url = product_data.get('Photo', '')
            photo_url = self._fix_photo_url(photo_url)

            result.append({
                'symbol': symbol,
                'name': product_data.get('Description', symbol),
                'manufacturer': product_data.get('Producer', ''),
                'barcode': product_data.get('EAN', ''),
                'stock': price_data.get('Amount', 0),
                'price': price,
                'currency': self.currency,
                'weight': weight_kg,
                'weight_unit': 'kg',
                'photo': photo_url,
            })

        return result

    def _parse_weight_to_kg(self, weight_value):
        """Convert weight value to kilograms"""
        if not weight_value:
            return 0.0

        try:
            weight_str = str(weight_value).strip().lower()
            if not weight_str:
                return 0.0

            import re
            numbers = re.findall(r'[\d.]+', weight_str)
            if not numbers:
                return 0.0

            weight_num = float(numbers[0])

            if 'kg' in weight_str:
                return weight_num
            elif 'g' in weight_str and 'kg' not in weight_str:
                return weight_num / 1000.0
            else:
                if weight_num < 1:
                    return weight_num
                else:
                    return weight_num / 1000.0

        except Exception as e:
            _logger.warning(f"Could not parse weight '{weight_value}': {str(e)}")
            return 0.0

    def _download_and_validate_image(self, image_url):
        """Download and validate an image from a URL"""
        if not image_url:
            return False

        if image_url.startswith('//'):
            image_url = f"https:{image_url}"
        elif not image_url.startswith('http'):
            image_url = f"https://{image_url}"

        for attempt in range(2):
            try:
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

                response = requests.get(
                    image_url,
                    timeout=20,
                    headers={
                        'User-Agent': 'Mozilla/5.0',
                        'Accept': 'image/*',
                    },
                    verify=False
                )

                if response.status_code != 200:
                    continue

                content_type = response.headers.get('Content-Type', '')
                if 'text/html' in content_type:
                    return False

                image_data = response.content
                if len(image_data) < 100:
                    continue

                img = Image.open(BytesIO(image_data))

                if img.mode == 'RGBA':
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[3])
                    img = background
                elif img.mode not in ('RGB', 'L'):
                    img = img.convert('RGB')
                elif img.mode == 'L':
                    img = img.convert('RGB')

                if img.size[0] > 1920 or img.size[1] > 1920:
                    img.thumbnail((1920, 1920), Image.Resampling.LANCZOS)

                output = BytesIO()
                img.save(output, format='JPEG', quality=85)
                validated_data = output.getvalue()
                output.close()

                return base64.b64encode(validated_data)

            except Exception as e:
                if attempt == 0:
                    time.sleep(1)
                continue

        return False

    def _get_or_create_supplier_partner(self):
        partner = self.env['res.partner'].search([
            ('name', '=', self.name),
            ('supplier_rank', '>', 0)
        ], limit=1)

        if not partner:
            partner = self.env['res.partner'].create({
                'name': self.name,
                'supplier_rank': 1,
                'is_company': True,
            })

        return partner

    def _create_new_product(self, product_data, partner, category, public_category=None, show_sale_price=False):
        """Create a new product in Odoo from API data"""
        Product = self.env['product.template']

        symbol = product_data.get('symbol')
        name = product_data.get('name', symbol)
        barcode = product_data.get('barcode')
        price = float(product_data.get('price', 0.0))
        stock = product_data.get('stock', 0)
        photo_url = product_data.get('photo', '')
        weight = product_data.get('weight', 0.0)

        _logger.info(f"Creating product: {symbol}")

        image_data = False
        if photo_url:
            try:
                image_data = self._download_and_validate_image(photo_url)
            except:
                pass

        cost_price = price
        sale_price = (price * 1.3) if show_sale_price else 0.0

        vals = {
            'name': name,
            'default_code': symbol,
            'api_external_id': symbol,
            'barcode': barcode if barcode else False,
            'type': 'product',
            'supplier_api_id': self.id,
            'supplier_api_category_id': category.id,
            'standard_price': cost_price,
            'list_price': sale_price,
            'weight': weight,
            'api_last_sync': fields.Datetime.now(),
            'sale_ok': True,
            'purchase_ok': True,
            'supplier_id': self.api_type,
        }

        if 'continue_seling' in Product._fields:
            vals['continue_seling'] = True
        if 'showDelivryMessage' in Product._fields:
            vals['showDelivryMessage'] = True
        if 'show_availability' in Product._fields:
            vals['show_availability'] = True
        if 'messageDelivryTimeStock' in Product._fields:
            vals['messageDelivryTimeStock'] = 'Ship 1-2 Days'
        if 'messageDelivryTimeRemoteStock' in Product._fields:
            vals['messageDelivryTimeRemoteStock'] = 'Ship 4-8 Days'
        if 'out_of_stock_message' in Product._fields:
            vals['out_of_stock_message'] = 'Ask for Availability'

        if photo_url:
            vals['image_url'] = self._fix_photo_url(photo_url)

        if image_data:
            vals['image_1920'] = image_data

        if category.odoo_category_id:
            vals['categ_id'] = category.odoo_category_id.id

        try:
            product = Product.sudo().create(vals)
            if not product or not product.id:
                return False
            product_id = product.id

            stock_qty = product_data.get('stock', 0)
            if stock_qty > 0:
                product._update_supplier_warehouse_qty(stock_qty)

            _logger.info(f"   Created: ID={product_id}")
        except Exception as e:
            _logger.error(f"   CREATE ERROR: {str(e)}")
            return False

        if category:
            try:
           
                if not category.public_category_id:
                    category._get_or_create_public_category()

                product_record = Product.browse(product_id)
        
                changed = product_record._sync_public_category(category)
                if changed:
                    pub_cat = category.public_category_id
                    _logger.info(
                        f"   Website category set: "
                        f"'{pub_cat.complete_name if pub_cat else '?'}'"
                    )
            except Exception as e:
                _logger.error(f"   Category error: {str(e)}")

        # try:
        #     self.env['product.supplierinfo'].sudo().create({
        #         'product_tmpl_id': product_id,
        #         'partner_id': partner.id,
        #         'price': cost_price,
        #         'min_qty': 1,
        #         'api_stock_quantity': stock,
        #     })
        #     product_record = Product.browse(product_id)
        #     product_record.invalidate_cache(['supplier_stock_qty'])
        #     product_record._compute_supplier_stock()
        # except:
        #     pass

        if stock > 0:
            try:
                Product.browse(product_id).sudo().write({'is_published': True})
            except:
                pass

        return product_id

    def _update_existing_product(self, product, product_data, partner, category, public_category=None, show_sale_price=False):
        """
        Update an existing product with latest data from API.
        Always updates — never skips.
        """
        stock = product_data.get('stock', 0)
        price = float(product_data.get('price', 0.0))
        photo_url = product_data.get('photo', '')
        weight = product_data.get('weight', 0.0)

        _logger.info(f"     Updating: {product.name}")
        _logger.info(f"        New stock: {stock}")
        _logger.info(f"        New price: {price}")

        cost_price = price
        update_vals = {
            'api_last_sync': fields.Datetime.now(),
            'standard_price': cost_price,
            'weight': weight,
        }

        if show_sale_price:
            if product.list_price == 0 or product.list_price < cost_price:
                update_vals['list_price'] = cost_price * 1.3
        else:
            update_vals['list_price'] = 0.0

        # Restore missing API links
        if not product.supplier_api_category_id:
            update_vals['supplier_api_category_id'] = category.id
        if not product.supplier_api_id:
            update_vals['supplier_api_id'] = self.id
        if not product.supplier_id or product.supplier_id == 'other':
            update_vals['supplier_id'] = self.api_type
        if not product.api_external_id:
            update_vals['api_external_id'] = product_data.get('symbol')

        # Image URL
        if photo_url and not product.image_url:
            update_vals['image_url'] = self._fix_photo_url(photo_url)

        # Download image if missing
        if photo_url and not product.image_1920:
            try:
                image_data = self._download_and_validate_image(photo_url)
                if image_data:
                    update_vals['image_1920'] = image_data
            except:
                pass

        # Add public category without overwriting other categories
        # if category:
        #     try:
        #         public_cat = category._get_or_create_public_category()
        #         # if public_cat and public_cat.id not in product.public_categ_ids.ids:
        #         #     update_vals['public_categ_ids'] = [(4, public_cat.id)]
               
        #         product._sync_public_category(category)
        #         _logger.info(f"        Website category: +'{public_cat.display_name}'")
        #     except Exception as e:
        #         _logger.error(f"        Category error: {str(e)}")

        # product.sudo().write(update_vals)
        # _logger.info(f"        Product fields updated")
      
        if category:
            try:
                if not category.public_category_id:
                    category._get_or_create_public_category()
            except Exception as e:
                _logger.error(f"        Category._get_or_create error: {str(e)}")

    
        product.sudo().write(update_vals)
        _logger.info(f"        Product fields updated")

       
        if category:
            try:
                product._sync_public_category(category)
            except Exception as e:
                _logger.error(f"        Sync public category error: {str(e)}")

        # old_lines = self.env['product.supplierinfo'].search([
        #     ('product_tmpl_id', '=', product.id),
        #     ('partner_id', '!=', partner.id),
        # ])
        # if old_lines:
        #     old_lines.sudo().unlink()
        #     _logger.info(f"        Removed {len(old_lines)} old supplier info lines")

        # Update supplier info stock
        # supplier_info = self.env['product.supplierinfo'].search([
        #     ('product_tmpl_id', '=', product.id),
        #     ('partner_id', '=', partner.id)
        # ], limit=1)

        # if supplier_info:
        #     old_stock = supplier_info.api_stock_quantity
        #     supplier_info.write({
        #         'api_stock_quantity': stock,
        #         'price': cost_price,
        #     })
        #     _logger.info(f"        Stock updated: {old_stock} -> {stock}")
        # else:
        #     self.env['product.supplierinfo'].sudo().create({
        #         'product_tmpl_id': product.id,
        #         'partner_id': partner.id,
        #         'price': cost_price,
        #         'min_qty': 1,
        #         'api_stock_quantity': stock,
        #     })
        #     _logger.info(f"        Stock created: {stock}")

        product._update_supplier_warehouse_qty(stock)

        should_publish = stock > 0
        try:
            product.sudo().write({'is_published': should_publish})
            _logger.info(f"        {'Published' if should_publish else 'Unpublished'}")
        except:
            pass

    def _force_publish_product(self, product):
        """Force publish a product"""
        try:
            product.sudo().write({'is_published': True})
            product.invalidate_cache(['is_published'])
            if product.supplier_api_category_id:
                product.supplier_api_category_id._auto_publish_category()
        except Exception as e:
            _logger.error(f"Publish error: {str(e)}")

    def _force_unpublish_product(self, product):
        """Force unpublish a product"""
        try:
            product.sudo().write({'is_published': False})
            product.invalidate_cache(['is_published'])
        except Exception as e:
            _logger.error(f"Unpublish error: {str(e)}")

    def _tme_import_products_batch(self, symbol_list, category, show_sale_price=False):
        """
        Import a batch of products with strict anti-duplicate logic.

        Search order: BARCODE first, then SKU if no barcode found.
        Returns: (created_ids, updated_ids)
        """
        if not symbol_list:
            return [], []

        _logger.info("=" * 80)
        _logger.info(f"BATCH IMPORT START - ANTI-DUPLICATE MODE")
        _logger.info(f"   Symbols  : {len(symbol_list)}")
        _logger.info(f"   Category : {category.name}")
        _logger.info(f"   Show Sale Price: {show_sale_price}")
        _logger.info("=" * 80)

        created_ids = []
        updated_ids = []

        try:
            products_data = self._fetch_product_details_batch(symbol_list)
            if not products_data:
                return [], []

            partner = self._get_or_create_supplier_partner()
            public_category = category._get_or_create_public_category()

            Product = self.env['product.template']

            for index, product_data in enumerate(products_data, 1):
                savepoint_name = f'product_import_{index}'

                try:
                    self.env.cr.execute(f'SAVEPOINT {savepoint_name}')

                    symbol = product_data.get('symbol')
                    barcode = product_data.get('barcode')
                    name = product_data.get('name', symbol)

                    _logger.info("-" * 50)
                    _logger.info(f"Product {index}/{len(products_data)}: {symbol}")
                    _logger.info(f"  Name   : {name}")
                    _logger.info(f"  SKU    : {symbol or 'N/A'}")
                    _logger.info(f"  Barcode: {barcode or 'N/A'}")

                    existing_product = None
                    sku_exists = False
                    barcode_exists = False

                    # Step 1: Search by barcode (global)
                    if barcode:
                        _logger.info(f"  Searching by Barcode globally...")
                        existing_product = Product.search([
                            ('barcode', '=', barcode)
                        ], limit=1)

                        if existing_product:
                            barcode_exists = True
                            _logger.info(f"  FOUND by Barcode: {existing_product.name} (ID: {existing_product.id})")

                    # Step 2: Search by SKU if not found by barcode
                    if not existing_product and symbol:
                        _logger.info(f"  Searching by SKU globally...")
                        existing_product = Product.search([
                            '|',
                            ('default_code', '=', symbol),
                            ('api_external_id', '=', symbol)
                        ], limit=1)

                        if existing_product:
                            sku_exists = True
                            _logger.info(f"  FOUND by SKU: {existing_product.name} (ID: {existing_product.id})")

                    if existing_product:
                        if barcode_exists and sku_exists:
                            rule = "Barcode=True & SKU=True"
                        elif barcode_exists:
                            rule = "Barcode=True & SKU=False"
                        elif sku_exists:
                            rule = "Barcode=False & SKU=True"
                        else:
                            rule = "Unknown"

                        _logger.info(f"  Rule: {rule} -> UPDATE")

                        # Restore missing API links
                        restore_vals = {}

                        if not existing_product.supplier_api_id:
                            restore_vals['supplier_api_id'] = self.id
                            _logger.info(f"     Restoring supplier_api_id")

                        if not existing_product.supplier_api_category_id:
                            restore_vals['supplier_api_category_id'] = category.id
                            _logger.info(f"     Restoring supplier_api_category_id")

                        if not existing_product.api_external_id:
                            restore_vals['api_external_id'] = symbol
                            _logger.info(f"     Restoring api_external_id")

                        if restore_vals:
                            existing_product.sudo().write(restore_vals)
                            _logger.info(f"     API links restored")

                        self._update_existing_product(
                            existing_product,
                            product_data,
                            partner,
                            category,
                            public_category,
                            show_sale_price
                        )

                        updated_ids.append(existing_product.id)
                        _logger.info(f"  UPDATED successfully")

                    else:
                        _logger.info(f"  Not found -> CREATE")

                        new_id = self._create_new_product(
                            product_data,
                            partner,
                            category,
                            public_category,
                            show_sale_price
                        )

                        if new_id:
                            created_ids.append(new_id)
                            _logger.info(f"  CREATED: ID={new_id}")
                        else:
                            self.env.cr.execute(f'ROLLBACK TO SAVEPOINT {savepoint_name}')
                            _logger.error(f"  CREATE FAILED")
                            continue

                    self.env.cr.execute(f'RELEASE SAVEPOINT {savepoint_name}')

                    # Commit every 10 products
                    if index % 10 == 0:
                        self.env.cr.commit()
                        _logger.info(f"  Committed {index}/{len(products_data)}")

                except Exception as e:
                    _logger.error(f"Error: {str(e)}", exc_info=True)
                    try:
                        self.env.cr.execute(f'ROLLBACK TO SAVEPOINT {savepoint_name}')
                    except:
                        pass
                    continue

            self.env.cr.commit()

            _logger.info("=" * 80)
            _logger.info(f"BATCH COMPLETE")
            _logger.info(f"   New products created      : {len(created_ids)}")
            _logger.info(f"   Existing products updated : {len(updated_ids)}")
            _logger.info(f"   Total processed           : {len(created_ids) + len(updated_ids)}")
            _logger.info("=" * 80)

            return created_ids, updated_ids

        except Exception as e:
            _logger.error(f"BATCH FAILED: {str(e)}", exc_info=True)
            self.env.cr.rollback()
            return [], []

    def _tme_sync_products(self, category):
        try:
            result = self._tme_api_call('/Products/GetSymbols', {
                'CategoryId': category.external_id
            })

            symbol_list = result.get('Data', {}).get('SymbolList', [])
            if not symbol_list:
                return

            for i in range(0, len(symbol_list), 50):
                batch = symbol_list[i:i+50]
                self._tme_import_products_batch(batch, category)

        except Exception as e:
            _logger.error(f"Error: {str(e)}")

    @api.model
    def _cron_download_missing_images(self):
        """CRON: Download missing product images"""
        _logger.info("[CRON] DOWNLOAD MISSING IMAGES")

        products = self.env['product.template'].search([
            ('supplier_api_id', '!=', False),
            ('image_1920', '=', False),
            ('api_external_id', '!=', False)
        ], limit=50)

        if not products:
            return

        success = 0
        for product in products:
            try:
                supplier = product.supplier_api_id
                params = {f'SymbolList[00]': product.api_external_id}
                result = supplier._tme_api_call('/Products/GetProducts', params)

                if result.get('Status') != 'OK':
                    continue

                products_data = result.get('Data', {}).get('ProductList', [])
                if not products_data:
                    continue

                photo_url = products_data[0].get('Photo', '')
                if not photo_url:
                    continue

                image_data = supplier._download_and_validate_image(photo_url)
                if image_data:
                    product.sudo().write({'image_1920': image_data})
                    success += 1
            except:
                continue

        self.env.cr.commit()

    def action_test_connection(self):
        self.ensure_one()
        try:
            result = self._tme_api_call('/Utils/Ping')
            if result.get('Status') == 'OK':
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Success!'),
                        'message': _('Connection successful!'),
                        'type': 'success',
                    }
                }
        except Exception as e:
            raise UserError(_('Connection failed: %s') % str(e))

    def _tme_fetch_categories(self):
        result = self._tme_api_call('/Products/GetCategories')
        data = result.get('Data', {})
        category_tree = data.get('CategoryTree')

        if not category_tree:
            raise UserError(_('No CategoryTree found'))

        self._update_category_recursive(category_tree, None)

 

    @api.model
    def create(self, vals):
        supplier = super(SupplierApiConfig, self).create(vals)
        _logger.info(f"New supplier API created: {supplier.name}")

        # try:
        #     supplier._clean_old_supplier_info()
        # except Exception as e:
        #     _logger.error(f"Clean supplier info failed: {str(e)}")

        return supplier

    # def unlink(self):
    #     """
    #     When deleting a supplier, clean ONLY the supplier info lines
    #     linked to this supplier. Do NOT touch other Odoo products.
    #     """
    #     for supplier in self:
    #         try:
    #             partner = self.env['res.partner'].search([
    #                 ('name', '=', supplier.name),
    #                 ('supplier_rank', '>', 0),
    #             ], limit=1)

    #             if partner:
    #                 api_product_ids = self.env['product.template'].search([
    #                     ('supplier_api_id', '=', supplier.id),
    #                 ]).ids

    #                 # if api_product_ids:
    #                 #     old_info = self.env['product.supplierinfo'].search([
    #                 #         ('partner_id', '=', partner.id),
    #                 #         ('product_tmpl_id', 'in', api_product_ids),
    #                 #     ])
    #                 #     if old_info:
    #                 #         old_info.sudo().unlink()
    #                 #         _logger.info(
    #                 #             f"Removed {len(old_info)} supplier info "
    #                 #             f"lines for {supplier.name}"
    #                 #         )
    #         except Exception as e:
    #             _logger.error(f"Unlink cleanup failed: {str(e)}")

    #     return super(SupplierApiConfig, self).unlink()

    def unlink(self):
        return super(SupplierApiConfig, self).unlink()
    
    # def _clean_old_supplier_info(self):
    #     """
    #     Clean old supplier info lines.
    #     Only affects products linked to THIS supplier via supplier_api_id.
    #     Does NOT touch other Odoo products.
    #     """
    #     self.ensure_one()

    #     partner = self._get_or_create_supplier_partner()

    #     products = self.env['product.template'].search([
    #         ('supplier_api_id', '=', self.id),
    #     ])

    #     if not products:
    #         _logger.info(f"  No products linked to this supplier yet")
    #         return

    #     cleaned = 0
    #     for product in products:
    #         old_info = self.env['product.supplierinfo'].search([
    #             ('product_tmpl_id', '=', product.id),
    #             ('partner_id', '!=', partner.id),
    #             ('partner_id.name', 'ilike', self.name),
    #         ])

    #         if old_info:
    #             old_info.sudo().unlink()
    #             cleaned += len(old_info)
    #             _logger.info(
    #                 f"  {product.default_code}: "
    #                 f"removed {len(old_info)} old supplier info lines"
    #             )

    #     if cleaned > 0:
    #         self.env.cr.commit()
    #         _logger.info(f"  Total removed: {cleaned} old supplier info lines")
    #     else:
    #         _logger.info(f"  No old supplier info to clean")

    def action_fetch_categories(self):
        self.ensure_one()
        try:
            if self.api_type == 'tme':
                self._tme_fetch_categories()

            try:
                self.action_fix_all_public_categories()
            except Exception as e:
                _logger.error(f"Fix public categories failed: {str(e)}")
            
            # try:
            #     self.action_clean_supplier_info()
            # except Exception as e:
            #     _logger.error(f"Clean supplier info failed: {str(e)}")

            return {'type': 'ir.actions.client', 'tag': 'reload'}

        except Exception as e:
            raise UserError(_('Failed: %s') % str(e))

    # def _refresh_all_synced_counts(self):
    #     """
    #     Recalculate synced_product_count for all categories.
    #     Called on fetch_categories only — not in the cron.
    #     """
    #     self.ensure_one()
    #     _logger.info(f"Refreshing synced counts: {self.name}")

    #     all_cats = self.env['supplier.api.category'].search([
    #         ('supplier_id', '=', self.id)
    #     ])

    #     # Reset all counters
    #     all_cats.sudo().write({'synced_product_count': 0, 'sync_enabled': False})

    #     # Fast SQL grouping for direct links
    #     self.env.cr.execute("""
    #         SELECT supplier_api_category_id, COUNT(*) as cnt
    #         FROM product_template
    #         WHERE supplier_api_category_id IN %s
    #         GROUP BY supplier_api_category_id
    #     """, (tuple(all_cats.ids) or (0,),))

    #     rows = self.env.cr.fetchall()
    #     direct_counts = {row[0]: row[1] for row in rows}

    #     for cat in all_cats:
    #         count = direct_counts.get(cat.id, 0)
    #         if count > 0:
    #             cat.sudo().write({
    #                 'synced_product_count': count,
    #                 'sync_enabled': True,
    #             })

    #     self.env.cr.commit()

    #     # For categories without direct links, search via barcode/SKU
    #     cats_without_direct = all_cats.filtered(
    #         lambda c: c.synced_product_count == 0 and c.product_count > 0
    #     )

    #     _logger.info(
    #         f"  Direct links   : {len(all_cats) - len(cats_without_direct)} categories\n"
    #         f"  Barcode/SKU search needed: {len(cats_without_direct)} categories"
    #     )

    #     for i, cat in enumerate(cats_without_direct, 1):
    #         cat._compute_synced_count_from_odoo()
    #         if i % 10 == 0:
    #             self.env.cr.commit()

    #     self.env.cr.commit()

    #     # ── NEW: activate sync_enabled on parent categories whose children are synced
    #     for cat in all_cats:
    #         if not cat.sync_enabled and cat.parent_path:
    #             has_synced_children = self.env['supplier.api.category'].search_count([
    #                 ('supplier_id', '=', self.id),
    #                 ('parent_path', 'like', cat.parent_path + '%'),
    #                 ('id', '!=', cat.id),
    #                 ('sync_enabled', '=', True),
    #             ]) > 0
    #             if has_synced_children:
    #                 cat.sudo().write({'sync_enabled': True})

    #     self.env.cr.commit()
    #     _logger.info(f"Refresh complete")
    # def _refresh_all_synced_counts(self):
    #     """
    #     Recalculate synced_product_count for all categories.
    #     Also repairs supplier_api_id on products that lost their link.
    #     """
    #     self.ensure_one()
    #     _logger.info(f"Refreshing synced counts: {self.name}")

    #     # ── ÉTAPE 0 : Réparer les produits qui ont supplier_id='tme'
    #     # mais supplier_api_id vide ──
    #     orphan_products = self.env['product.template'].search([
    #         ('supplier_id', '=', self.api_type),
    #         ('supplier_api_id', '=', False),
    #     ])
    #     if orphan_products:
    #         orphan_products.sudo().write({'supplier_api_id': self.id})
    #         self.env.cr.commit()
    #         _logger.info(
    #             f"  Repaired supplier_api_id on "
    #             f"{len(orphan_products)} orphan products"
    #         )

    #     # ── ÉTAPE 1 : Reset tous les compteurs ──
    #     all_cats = self.env['supplier.api.category'].search([
    #         ('supplier_id', '=', self.id)
    #     ])

    #     all_cats.sudo().write({'synced_product_count': 0, 'sync_enabled': False})

    #     # Fast SQL grouping for direct links
    #     self.env.cr.execute("""
    #         SELECT supplier_api_category_id, COUNT(*) as cnt
    #         FROM product_template
    #         WHERE supplier_api_category_id IN %s
    #         GROUP BY supplier_api_category_id
    #     """, (tuple(all_cats.ids) or (0,),))

    #     rows = self.env.cr.fetchall()
    #     direct_counts = {row[0]: row[1] for row in rows}

    #     for cat in all_cats:
    #         count = direct_counts.get(cat.id, 0)
    #         if count > 0:
    #             cat.sudo().write({
    #                 'synced_product_count': count,
    #                 'sync_enabled': True,
    #             })

    #     self.env.cr.commit()

    #     # For categories without direct links, search via barcode/SKU
    #     cats_without_direct = all_cats.filtered(
    #         lambda c: c.synced_product_count == 0 and c.product_count > 0
    #     )

    #     _logger.info(
    #         f"  Direct links   : {len(all_cats) - len(cats_without_direct)} categories\n"
    #         f"  Barcode/SKU search needed: {len(cats_without_direct)} categories"
    #     )

    #     for i, cat in enumerate(cats_without_direct, 1):
    #         cat._compute_synced_count_from_odoo()
    #         if i % 10 == 0:
    #             self.env.cr.commit()

    #     self.env.cr.commit()

    #     # Activer sync_enabled sur les catégories parentes dont les enfants sont synced
    #     for cat in all_cats:
    #         if not cat.sync_enabled and cat.parent_path:
    #             has_synced_children = self.env['supplier.api.category'].search_count([
    #                 ('supplier_id', '=', self.id),
    #                 ('parent_path', 'like', cat.parent_path + '%'),
    #                 ('id', '!=', cat.id),
    #                 ('sync_enabled', '=', True),
    #             ]) > 0
    #             if has_synced_children:
    #                 cat.sudo().write({'sync_enabled': True})

    #     self.env.cr.commit()
    #     _logger.info(f"Refresh complete")

    # def action_refresh_synced_counts(self):
    #     """
    #     Button: Recalculate synced_product_count for all categories.
    #     Assigns existing Odoo products to their TME categories.
    #     """
    #     self.ensure_one()

    #     _logger.info("=" * 60)
    #     _logger.info(f"ACTION REFRESH SYNCED COUNTS: {self.name}")
    #     _logger.info("=" * 60)

    #     try:
    #         self._refresh_all_synced_counts()
    #     except Exception as e:
    #         raise UserError(_('Refresh failed: %s') % str(e))

    #     all_cats = self.env['supplier.api.category'].search([
    #         ('supplier_id', '=', self.id),
    #     ])
    #     cats_with_products = len(all_cats.filtered(lambda c: c.synced_product_count > 0))
    #     total_found = sum(all_cats.mapped('synced_product_count'))

    #     _logger.info("=" * 60)
    #     _logger.info(f"DONE: {cats_with_products} categories with products in Odoo")
    #     _logger.info(f"Total products matched: {total_found}")
    #     _logger.info("=" * 60)

    #     return {
    #         'type': 'ir.actions.client',
    #         'tag': 'display_notification',
    #         'params': {
    #             'title': _('Refresh Complete!'),
    #             'message': _(
    #                 'Categories with products in Odoo: %d\n'
    #                 'Total products matched: %d'
    #             ) % (cats_with_products, total_found),
    #             'type': 'success',
    #             'sticky': True,
    #         }
    #     }
    def _refresh_all_synced_counts(self):
        """
        Recalculate synced_product_count for all categories.

        """
        self.ensure_one()
        _logger.info(f"Refreshing synced counts: {self.name}")

      
        orphan_products = self.env['product.template'].search([
            ('supplier_id', '=', self.api_type),
            ('supplier_api_id', '=', False),
        ])
        if orphan_products:
            orphan_products.sudo().write({'supplier_api_id': self.id})
            self.env.cr.commit()
            _logger.info(
                f"  [0a] Repaired supplier_api_id on "
                f"{len(orphan_products)} orphan products"
            )
        else:
            _logger.info(f"  [0a] No orphan products found")

       
        products_without_api_cat = self.env['product.template'].search([
            ('supplier_api_id', '=', self.id),
            ('supplier_api_category_id', '=', False),
            ('public_categ_ids', '!=', False),
        ])

        if products_without_api_cat:
            _logger.info(
                f"  [0b] Trying to assign supplier_api_category_id "
                f"for {len(products_without_api_cat)} products via public_categ_ids..."
            )
            assigned = 0
            for product in products_without_api_cat:
            
                best_api_cat = None
                best_depth = -1

                for pub_cat in product.public_categ_ids:
                    api_cat = self.env['supplier.api.category'].search([
                        ('supplier_id', '=', self.id),
                        ('public_category_id', '=', pub_cat.id),
                    ], limit=1)

                    if api_cat:
                        # Compter la profondeur via parent_path
                        depth = api_cat.parent_path.count('/') if api_cat.parent_path else 0
                        if depth > best_depth:
                            best_depth = depth
                            best_api_cat = api_cat

                if best_api_cat:
                    product.sudo().write({
                        'supplier_api_category_id': best_api_cat.id,
                    })
                    assigned += 1
                    _logger.info(
                        f"    {product.default_code or product.name}: "
                        f"assigned to '{best_api_cat.complete_name}'"
                    )

            if assigned:
                self.env.cr.commit()
                _logger.info(f"  [0b] Assigned supplier_api_category_id to {assigned} products")
            else:
                _logger.info(f"  [0b] No assignment possible via public_categ_ids")
        else:
            _logger.info(f"  [0b] No products need supplier_api_category_id assignment")

     
        all_cats = self.env['supplier.api.category'].search([
            ('supplier_id', '=', self.id)
        ])

        if not all_cats:
            _logger.info("  No active categories, skipping.")
            return

        all_cats.sudo().write({'synced_product_count': 0, 'sync_enabled': False})

      
        self.env.cr.execute("""
            SELECT supplier_api_category_id, COUNT(*) as cnt
            FROM product_template
            WHERE supplier_api_category_id IN %s
            GROUP BY supplier_api_category_id
        """, (tuple(all_cats.ids) or (0,),))

        rows = self.env.cr.fetchall()
        direct_counts = {row[0]: row[1] for row in rows}

        cats_with_direct = 0
        for cat in all_cats:
            count = direct_counts.get(cat.id, 0)
            if count > 0:
                cat.sudo().write({
                    'synced_product_count': count,
                    'sync_enabled': True,
                })
                cats_with_direct += 1

        self.env.cr.commit()
        _logger.info(f"  [2] Direct links found: {cats_with_direct} categories")

      
        cats_without_direct = all_cats.filtered(
            lambda c: c.synced_product_count == 0 and c.product_count > 0
        )

        _logger.info(
            f"  [3] Barcode/SKU search needed: "
            f"{len(cats_without_direct)} categories"
        )

        for i, cat in enumerate(cats_without_direct, 1):
            try:
                cat._compute_synced_count_from_odoo()
            except Exception as e:
                _logger.error(f"  [3] {cat.complete_name}: {str(e)}")
            if i % 10 == 0:
                self.env.cr.commit()
                _logger.info(f"  [3] ... {i}/{len(cats_without_direct)}")

        self.env.cr.commit()

       
        activated_parents = 0

       
        cats_with_products = all_cats.filtered(
            lambda c: c.synced_product_count > 0
        )

       
        for leaf_cat in cats_with_products:
            parent = leaf_cat.parent_id
            while parent:
                if not parent.sync_enabled:
                    parent.sudo().write({'sync_enabled': True})
                    activated_parents += 1
                    _logger.info(
                        f"  [4] sync_enabled=True (ancêtre de '{leaf_cat.complete_name}'): "
                        f"'{parent.complete_name}'"
                    )
                parent = parent.parent_id

        self.env.cr.commit()
        _logger.info(f"  [4] Activated {activated_parents} parent categories")
     
        final_cats_synced = self.env['supplier.api.category'].search_count([
            ('supplier_id', '=', self.id),
            ('sync_enabled', '=', True),
        ])
        final_products = self.env['product.template'].search_count([
            ('supplier_api_id', '=', self.id),
        ])

        _logger.info(
            f"  ══ REFRESH COMPLETE ══\n"
            f"  Categories with sync_enabled : {final_cats_synced}\n"
            f"  Total products in Odoo       : {final_products}"
        )


    def action_refresh_synced_counts(self):
        """
        Button: Recalculate synced_product_count for all categories.
        Assigns existing Odoo products to their TME categories.
        """
        self.ensure_one()

        _logger.info("=" * 60)
        _logger.info(f"ACTION REFRESH SYNCED COUNTS: {self.name}")
        _logger.info("=" * 60)

        try:
            self._refresh_all_synced_counts()
        except Exception as e:
            raise UserError(_('Refresh failed: %s') % str(e))

    
        self.invalidate_cache(['synced_products', 'products_without_category'])
     
        self._compute_stats()

        all_cats = self.env['supplier.api.category'].search([
            ('supplier_id', '=', self.id),
        ])
        cats_with_products = len(all_cats.filtered(lambda c: c.synced_product_count > 0))
        total_found = sum(all_cats.mapped('synced_product_count'))

      
        total_products_in_odoo = self.env['product.template'].search_count([
            ('supplier_api_id', '=', self.id),
        ])

        _logger.info("=" * 60)
        _logger.info(f"DONE: {cats_with_products} categories with products in Odoo")
        _logger.info(f"Total products in Odoo (supplier_api_id): {total_products_in_odoo}")
        _logger.info(f"Total from category counts: {total_found}")
        _logger.info("=" * 60)

      
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'supplier.api.config',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'main',
            'flags': {'mode': 'readonly'},
        }
    
    
    # def action_clean_supplier_info(self):
    #     """
    #     Remove all duplicate/old supplier info lines for products of this supplier.
    #     Keeps ONLY the line belonging to the current partner.
    #     Run this once to clean up existing data.
    #     """
    #     self.ensure_one()
    #     partner = self._get_or_create_supplier_partner()

    #     products = self.env['product.template'].search([
    #         ('supplier_id', '=', self.api_type),
    #     ])

    #     cleaned = 0
    #     for product in products:
    #         old_lines = self.env['product.supplierinfo'].search([
    #             ('product_tmpl_id', '=', product.id),
    #             ('partner_id', '!=', partner.id),
    #         ])
    #         if old_lines:
    #             old_lines.sudo().unlink()
    #             cleaned += len(old_lines)

    #     self.env.cr.commit()
    #     _logger.info(f"action_clean_supplier_info: removed {cleaned} old lines for {self.name}")

    #     return {
    #         'type': 'ir.actions.client',
    #         'tag': 'display_notification',
    #         'params': {
    #             'title': _('Cleanup Complete'),
    #             'message': _(
    #                 'Old supplier info lines removed: %d\n'
    #                 'Products checked: %d'
    #             ) % (cleaned, len(products)),
    #             'type': 'success',
    #             'sticky': True,
    #         }
    #     }


    def action_view_synced_products(self):
        self.ensure_one()
        return {
            'name': _('Products Synced: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'product.template',
            'view_mode': 'kanban,tree,form',
            # 'domain': [('supplier_id', '=', self.api_type)],
            # ✅ CORRECT
            'domain': [('supplier_api_id', '=', self.id)],
            'context': {
                'search_default_group_by_category': 1,
            },
        }

    @api.model
    def _cron_update_stock_and_prices(self):
        """HOURLY CRON: Update stock and prices for all imported products"""
        _logger.info("[CRON HOURLY] START")

        for supplier in self.search([('active', '=', True), ('auto_sync', '=', True)]):
            try:
                products = self.env['product.template'].search([
                    ('supplier_api_id', '=', supplier.id),
                    ('api_external_id', '!=', False),
                ])
               
               
                if not products:
                    continue

                _logger.info(f"  {supplier.name}: {len(products)} products")

                for i in range(0, len(products), 50):
                    try:
                        supplier._batch_update_stock_and_price(products[i:i+50])
                    except Exception as e:
                        _logger.error(f"  batch {i}: {str(e)}")
                        self.env.cr.rollback()

                supplier.write({'last_sync_date': fields.Datetime.now()})
                self.env.cr.commit()

            except Exception as e:
                _logger.error(f"{supplier.name}: {str(e)}")
                self.env.cr.rollback()

        _logger.info("[CRON HOURLY] DONE")

    def _batch_update_stock_and_price(self, products):
        """
        Update a batch of 50 products:
        - stock (Amount)
        - price (PriceValue)
        - name (Description)
        - manufacturer (Producer)
        - barcode (EAN)
        - weight (Weight)
        - photo (Photo)
        - public_categ_ids
        - published/unpublished based on stock
        """
        if not products:
            return

        params_price = {}
        params_detail = {}
        product_map = {}

        for i, p in enumerate(products):
            if p.api_external_id:
                key = f'SymbolList[{i:02d}]'
                params_price[key] = p.api_external_id
                params_detail[key] = p.api_external_id
                product_map[p.api_external_id] = p

        if not params_price:
            return

        # API call: prices and stock
        params_price['Currency'] = self.currency
        price_result = self._tme_api_call('/Products/GetPricesAndStocks', params_price)
        price_list_data = price_result.get('Data', {}).get('ProductList', [])
        prices = {item['Symbol']: item for item in price_list_data}

        # API call: product details
        detail_result = self._tme_api_call('/Products/GetProducts', params_detail)
        detail_list_data = detail_result.get('Data', {}).get('ProductList', [])
        details = {item['Symbol']: item for item in detail_list_data}

        # partner = self._get_or_create_supplier_partner()

        for symbol, product in product_map.items():
            try:
                p_data = details.get(symbol, {})
                pr_data = prices.get(symbol, {})

                quantity = pr_data.get('Amount', 0)
                price_vals = pr_data.get('PriceList', [])
                cost_price = price_vals[0].get('PriceValue', 0.0) if price_vals else 0.0

                name = p_data.get('Description') or product.name
                manufacturer = p_data.get('Producer', '')
                barcode = p_data.get('EAN', '')
                photo_url = self._fix_photo_url(p_data.get('Photo', ''))
                weight_kg = self._parse_weight_to_kg(p_data.get('Weight', ''))

                update_vals = {
                    'name': name,
                    'standard_price': cost_price,
                    'weight': weight_kg,
                    'api_last_sync': fields.Datetime.now(),
                }

                if manufacturer and 'manufacturer' in product._fields:
                    update_vals['manufacturer'] = manufacturer

                if barcode and not product.barcode:
                    update_vals['barcode'] = barcode

                if product.list_price > 0:
                    update_vals['list_price'] = cost_price * 1.3

                if photo_url:
                    update_vals['image_url'] = photo_url

                # Fix public_categ_ids if path is broken
                # api_cat = product.supplier_api_category_id
                # if api_cat:
                #     pub_cat = (
                #         api_cat.public_category_id
                #         or api_cat._get_or_create_public_category()
                #     )
                #     if pub_cat:
                #         # Detect broken path (too short) and rebuild
                #         if (pub_cat.parent_id and not pub_cat.parent_id.parent_id
                #                 and api_cat.parent_id and api_cat.parent_id.parent_id):
                #             api_cat.sudo().write({'public_category_id': False})
                #             pub_cat = api_cat._get_or_create_public_category()

                #         # if pub_cat.id not in product.public_categ_ids.ids:
                #         #     update_vals['public_categ_ids'] = [(4, pub_cat.id)]
           
                #     product.sudo().write(update_vals)
                #     product._sync_public_category(api_cat)

                api_cat = product.supplier_api_category_id

                if api_cat:
             
                    pub_cat = api_cat.public_category_id
                    if not pub_cat:
                        pub_cat = api_cat._get_or_create_public_category()

                
                    if (pub_cat
                            and pub_cat.parent_id
                            and not pub_cat.parent_id.parent_id
                            and api_cat.parent_id
                            and api_cat.parent_id.parent_id):
                        _logger.info(
                            f"  {symbol}: broken path detected, rebuilding "
                            f"'{api_cat.complete_name}'"
                        )
                        api_cat.sudo().write({'public_category_id': False})
                        api_cat._get_or_create_public_category()

              
                product.sudo().write(update_vals)

              
                if api_cat:
                    try:
                        product._sync_public_category(api_cat)
                    except Exception as e:
                        _logger.error(f"  {symbol}: _sync_public_category error: {str(e)}")
                # product.sudo().write(update_vals)
                
                # old_lines = self.env['product.supplierinfo'].search([
                #     ('product_tmpl_id', '=', product.id),
                #     ('partner_id', '!=', partner.id),
                # ])
                # if old_lines:
                #     old_lines.sudo().unlink()

                # s_info = self.env['product.supplierinfo'].search([
                #     ('product_tmpl_id', '=', product.id),
                #     ('partner_id', '=', partner.id),
                # ], limit=1)

                # if s_info:
                #     s_info.write({'api_stock_quantity': quantity, 'price': cost_price})
                # else:
                #     self.env['product.supplierinfo'].sudo().create({
                #         'product_tmpl_id': product.id,
                #         'partner_id': partner.id,
                #         'price': cost_price,
                #         'min_qty': 1,
                #         'api_stock_quantity': quantity,
                #     })

                product._update_supplier_warehouse_qty(quantity)

                should_publish = quantity > 0
                if product.is_published != should_publish:
                    product.sudo().write({'is_published': should_publish})

                # Download image if missing
                if photo_url and not product.image_1920:
                    try:
                        img = self._download_and_validate_image(photo_url)
                        if img:
                            product.sudo().write({'image_1920': img})
                    except Exception:
                        pass

            except Exception as e:
                _logger.error(f"  {symbol}: {str(e)}")
                continue

        self.env.cr.commit()

    @api.model
    def _cron_full_sync(self):
        """
        DAILY CRON — Full mirror sync with TME API.

        What this cron DOES:
        - Categories: creates new, renames existing, updates product_count
        - Already imported products: updates price, stock, name, manufacturer,
          barcode, weight, photo, public_categ_ids, published/unpublished
        - Products removed from TME: unpublished in Odoo

        What this cron does NOT do:
        - Import new products from API to Odoo (manual decision by the client)
        """
        _logger.info("[CRON DAILY] START")

        for supplier in self.search([('active', '=', True), ('auto_sync', '=', True)]):
            try:
                _logger.info(f"\n{'='*60}\n{supplier.name}\n{'='*60}")

                # Step 1: Sync category tree
                supplier._sync_categories_only()

                # Step 2: Update all already-imported products
                supplier._full_update_existing_products()

                # Step 3: Detect and unpublish removed products
                supplier._sync_removed_and_moved_products()

                # Step 4: Fix public_categ_ids for all products
                supplier.action_fix_all_public_categories()

                # Step 5: Refresh synced_product_count
                try:
                    supplier._refresh_all_synced_counts()
                    _logger.info(f"  synced_product_count refreshed")
                except Exception as e:
                    _logger.error(f"  Refresh counts failed: {str(e)}")
                
                # Step 6: Clean old supplier info lines 
                # try:
                #     supplier.action_clean_supplier_info()
                # except Exception as e:
                #     _logger.error(f"  Clean supplier info failed: {str(e)}")

                supplier.invalidate_cache(['synced_products', 'products_without_category'])
                supplier.write({'last_sync_date': fields.Datetime.now()})
                self.env.cr.commit()
                _logger.info(f"{supplier.name} done")

            except Exception as e:
                _logger.error(f"{supplier.name}: {str(e)}", exc_info=True)
                self.env.cr.rollback()

        _logger.info("[CRON DAILY] DONE")

    def _full_update_existing_products(self):
        """
        Update ALL fields for already imported products.

        Fields updated: name, manufacturer, barcode, weight, photo,
        standard_price, list_price, stock, supplier_api_category_id
        (if moved), public_categ_ids, is_published.
        """
        self.ensure_one()

        # products = self.env['product.template'].search([
        #     ('supplier_id', '=', self.api_type),
        #     ('api_external_id', '!=', False),
        # ])
        # ✅ CORRECT
        products = self.env['product.template'].search([
            ('supplier_api_id', '=', self.id),
            ('api_external_id', '!=', False),
        ])

        if not products:
            _logger.info("  No products to update")
            return

        _logger.info(f"  Updating {len(products)} existing products...")

        # partner = self._get_or_create_supplier_partner()
        batch_size = 50

        for i in range(0, len(products), batch_size):
            batch = products[i:i + batch_size]
            try:
                # self._full_update_batch(batch, partner)
                self._full_update_batch(batch)
                self.env.cr.commit()
                _logger.info(f"  ... {min(i + batch_size, len(products))}/{len(products)}")
            except Exception as e:
                _logger.error(f"  Batch {i}: {str(e)}")
                self.env.cr.rollback()

        _logger.info(f"  Full update done")

    # def _full_update_batch(self, products, partner):
    def _full_update_batch(self, products):
        if not products:
            return

        params = {}
        product_map = {}
        for i, p in enumerate(products):
            if p.api_external_id:
                key = f'SymbolList[{i:02d}]'
                params[key] = p.api_external_id
                product_map[p.api_external_id] = p

        if not params:
            return

        # API call 1: product details (includes CategoryId)
        detail_result = self._tme_api_call('/Products/GetProducts', params)
        details = {
            item['Symbol']: item
            for item in detail_result.get('Data', {}).get('ProductList', [])
        }

        # API call 2: prices and stock
        params_price = dict(params)
        params_price['Currency'] = self.currency
        price_result = self._tme_api_call('/Products/GetPricesAndStocks', params_price)
        prices = {
            item['Symbol']: item
            for item in price_result.get('Data', {}).get('ProductList', [])
        }

        for symbol, product in product_map.items():
            try:
                p_data = details.get(symbol, {})
                pr_data = prices.get(symbol, {})

                name = p_data.get('Description') or product.name
                manufacturer = p_data.get('Producer', '')
                barcode = p_data.get('EAN', '')
                photo_url = self._fix_photo_url(p_data.get('Photo', ''))
                weight_kg = self._parse_weight_to_kg(p_data.get('Weight', ''))
                quantity = pr_data.get('Amount', 0)
                price_vals = pr_data.get('PriceList', [])
                cost_price = price_vals[0].get('PriceValue', 0.0) if price_vals else 0.0

                update_vals = {
                    'name': name,
                    'standard_price': cost_price,
                    'weight': weight_kg,
                    'api_last_sync': fields.Datetime.now(),
                }

                if manufacturer and 'manufacturer' in product._fields:
                    update_vals['manufacturer'] = manufacturer

                if barcode and not product.barcode:
                    update_vals['barcode'] = barcode

                if product.list_price > 0:
                    update_vals['list_price'] = cost_price * 1.3

                if photo_url:
                    update_vals['image_url'] = photo_url

                # Detect product moved to another category via CategoryId
                api_category_external_id = str(p_data.get('CategoryId', ''))
                correct_category = product.supplier_api_category_id

                if api_category_external_id:
                    tme_category = self.env['supplier.api.category'].search([
                        ('supplier_id', '=', self.id),
                        ('external_id', '=', api_category_external_id),
                    ], limit=1)

                    if tme_category and tme_category != product.supplier_api_category_id:
                        correct_category = tme_category
                        update_vals['supplier_api_category_id'] = tme_category.id
                        _logger.info(
                            f"  {symbol}: moved "
                            f"'{product.supplier_api_category_id.name}' "
                            f"-> '{tme_category.name}'"
                        )

                # Update public_categ_ids based on correct (current or new) category
                old_category = product.supplier_api_category_id

                # Préparer la public category de la catégorie cible
                if correct_category:
                    try:
                        pub_cat = correct_category.public_category_id
                        if not pub_cat:
                            pub_cat = correct_category._get_or_create_public_category()

                        # Détecter et réparer hiérarchie cassée
                        if (pub_cat
                                and pub_cat.parent_id
                                and not pub_cat.parent_id.parent_id
                                and correct_category.parent_id
                                and correct_category.parent_id.parent_id):
                            _logger.info(
                                f"  {symbol}: broken path, rebuilding "
                                f"'{correct_category.complete_name}'"
                            )
                            correct_category.sudo().write({'public_category_id': False})
                            correct_category._get_or_create_public_category()
                    except Exception as e:
                        _logger.error(
                            f"  {symbol}: prepare public_category error: {str(e)}"
                        )

                # Write champs métier
                product.sudo().write(update_vals)

                # Sync public_categ_ids avec old_category pour détecter déplacement
                if correct_category:
                    try:
                        product._sync_public_category(
                            correct_category,
                            old_api_category=old_category if old_category != correct_category else None
                        )
                    except Exception as e:
                        _logger.error(f"  {symbol}: _sync_public_category error: {str(e)}")
                # product.sudo().write(update_vals)
                
                 # old_lines = self.env['product.supplierinfo'].search([
                #     ('product_tmpl_id', '=', product.id),
                #     ('partner_id', '!=', partner.id),
                # ])
                # if old_lines:
                #     old_lines.sudo().unlink()

                # s_info = self.env['product.supplierinfo'].search([
                #     ('product_tmpl_id', '=', product.id),
                #     ('partner_id', '=', partner.id),
                # ], limit=1)

                # if s_info:
                #     s_info.write({'api_stock_quantity': quantity, 'price': cost_price})
                # else:
                #     self.env['product.supplierinfo'].sudo().create({
                #         'product_tmpl_id': product.id,
                #         'partner_id': partner.id,
                #         'price': cost_price,
                #         'min_qty': 1,
                #         'api_stock_quantity': quantity,
                #     })

                product._update_supplier_warehouse_qty(quantity)

                should_publish = quantity > 0
                if product.is_published != should_publish:
                    product.sudo().write({'is_published': should_publish})

                # Download image if URL changed or image missing
                if photo_url and photo_url != product.image_url:
                    try:
                        img = self._download_and_validate_image(photo_url)
                        if img:
                            product.sudo().write({'image_1920': img})
                    except Exception:
                        pass
                elif photo_url and not product.image_1920:
                    try:
                        img = self._download_and_validate_image(photo_url)
                        if img:
                            product.sudo().write({'image_1920': img})
                    except Exception:
                        pass

            except Exception as e:
                _logger.error(f"  {symbol}: {str(e)}")
                continue

    def _find_category_for_symbol(self, symbol):
        """
        Find which TME category a symbol currently belongs to.
        Used to detect if a product has been moved by the supplier.
        Strategy: call GetProducts and read CategoryId from the API response.
        """
        try:
            params = {'SymbolList[00]': symbol}
            result = self._tme_api_call('/Products/GetProducts', params)
            product_list = result.get('Data', {}).get('ProductList', [])

            if not product_list:
                return None

            api_category_id = str(product_list[0].get('CategoryId', ''))
            if not api_category_id:
                return None

            category = self.env['supplier.api.category'].search([
                ('supplier_id', '=', self.id),
                ('external_id', '=', api_category_id),
            ], limit=1)

            return category or None

        except Exception as e:
            _logger.error(f"  _find_category_for_symbol({symbol}): {str(e)}")
            return None

    def _sync_removed_and_moved_products(self):
        self.ensure_one()
        _logger.info("  Checking removed products from TME...")

        unpublished = 0
        removed_products_info = []

        categories_with_products = self.env['supplier.api.category'].search([
            ('supplier_id', '=', self.id),
            ('synced_product_count', '>', 0),
        ])

        for category in categories_with_products:
            try:
                result = self._tme_api_call('/Products/GetSymbols', {
                    'CategoryId': category.external_id
                })
                api_symbols = set(result.get('Data', {}).get('SymbolList', []))

                odoo_products = self.env['product.template'].search([
                    ('supplier_api_category_id', '=', category.id),
                    ('api_external_id', '!=', False),
                ])

                for product in odoo_products:
                    if product.api_external_id not in api_symbols:
                        product.sudo().write({'is_published': False})
                        unpublished += 1

                        removed_products_info.append({
                            'sku': product.default_code or product.api_external_id,
                            'name': product.name,
                            'category': category.complete_name,
                        })

                        _logger.info(
                            f"    Removed from TME: "
                            f"{product.default_code} | {product.name} "
                            f"| Category: {category.complete_name}"
                        )

            except Exception as e:
                _logger.error(f"  {category.name}: {str(e)}")

        self.env.cr.commit()

        # Create a notification if products were unpublished
        if removed_products_info:
            lines = '\n'.join([
                f"- {p['sku']} - {p['name']} (category: {p['category']})"
                for p in removed_products_info[:20]
            ])
            if len(removed_products_info) > 20:
                lines += f"\n... and {len(removed_products_info) - 20} more"

            self.env['mail.activity'].sudo().create({
                'res_model_id': self.env['ir.model']._get('supplier.api.config').id,
                'res_id': self.id,
                'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                'summary': f'{unpublished} products removed from TME',
                'note': (
                    f'<p>The following products have been removed from TME '
                    f'and automatically unpublished on the website:</p>'
                    f'<pre>{lines}</pre>'
                    f'<p>You can delete them manually in Odoo if needed.</p>'
                ),
                'user_id': self.env.ref('base.user_admin').id,
            })

            _logger.info(f"  Notification created: {unpublished} products unpublished")

        _logger.info(f"  {unpublished} products unpublished")

    def _sync_categories_only(self):
        """
        Update product_count for existing categories.
        Create new categories that appeared at the supplier.
        Does NOT delete disappeared categories (data safety).
        """
        self.ensure_one()
        _logger.info("  Syncing categories...")

        result = self._tme_api_call('/Products/GetCategories')
        category_tree = result.get('Data', {}).get('CategoryTree')
        if not category_tree:
            _logger.warning("  No CategoryTree returned")
            return

        self._update_category_recursive(category_tree, None)
        self.env.cr.commit()
        _logger.info("  Categories synced")

    def _update_category_recursive(self, category_data, parent_odoo_id):
        """Update existing category or create if new."""
        if not isinstance(category_data, dict):
            return

        cat_id = str(category_data.get('Id', ''))
        if not cat_id:
            return

        Category = self.env['supplier.api.category']
        existing = Category.search([
            ('supplier_id', '=', self.id),
            ('external_id', '=', cat_id),
        ], limit=1)

        product_count = category_data.get('TotalProducts', 0)

        if existing:
            existing.write({
                'name': category_data.get('Name', existing.name),
                'product_count': product_count,
            })
            cat_odoo_id = existing.id
        else:
            new_cat = Category.create({
                'supplier_id': self.id,
                'external_id': cat_id,
                'name': category_data.get('Name', f'Category {cat_id}'),
                'parent_id': parent_odoo_id,
                'product_count': product_count,
            })
            cat_odoo_id = new_cat.id
            _logger.info(f"    New category: {category_data.get('Name')}")

        for child in category_data.get('SubTree', []):
            self._update_category_recursive(child, cat_odoo_id)

    def action_fix_all_public_categories(self):
        self.ensure_one()
        _logger.info(f"Fixing public_categ_ids for: {self.name}")

      
        all_cats = self.env['supplier.api.category'].search(
            [('supplier_id', '=', self.id)], order='parent_path'
        )
        for cat in all_cats:
            try:
                cat._get_or_create_public_category()
            except Exception as e:
                _logger.error(f"  {cat.complete_name}: {str(e)}")

        self.env.cr.commit()
        _logger.info(f"  public_category_id rempli sur toutes les catégories")

      
        products = self.env['product.template'].search([
            ('supplier_api_id', '=', self.id),
            ('supplier_api_category_id', '!=', False),
        ])

        fixed = 0
        no_pub_cat = 0

        for product in products:
            try:
                api_cat = product.supplier_api_category_id

                pub_cat = api_cat.public_category_id
                if not pub_cat:
                    pub_cat = api_cat._get_or_create_public_category()

                if not pub_cat:
                    no_pub_cat += 1
                    _logger.warning(
                        f"  {product.default_code}: "
                        f"public_category_id toujours vide sur '{api_cat.complete_name}'"
                    )
                    continue

             
                changed = product._sync_public_category(api_cat)
                if changed:
                    fixed += 1
                    _logger.info(
                        f"  {product.default_code}: "
                        f"'{api_cat.complete_name}' "
                        f"-> public_categ_ids mis à jour"
                    )

            except Exception as e:
                _logger.error(f"  {product.default_code}: {str(e)}")

        self.env.cr.commit()
        _logger.info(
            f"  Résultat: {fixed} modifiés | "
            f"{len(products) - fixed - no_pub_cat} déjà corrects | "
            f"{no_pub_cat} sans public_category_id"
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Categories Fixed!'),
                'message': _(
                    'Fixed: %d\nAlready correct: %d\nNo category: %d'
                ) % (fixed, len(products) - fixed - no_pub_cat, no_pub_cat),
                'type': 'success',
                'sticky': True,
            }
        }