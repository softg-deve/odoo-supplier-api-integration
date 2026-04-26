# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class SupplierApiCategory(models.Model):
    _name = 'supplier.api.category'
    _description = 'Supplier API Category'
    _parent_name = 'parent_id'
    _parent_store = True
    _rec_name = 'complete_name'
    _order = 'complete_name'

    name = fields.Char('Category Name', required=True)
    complete_name = fields.Char('Complete Name', compute='_compute_complete_name',
                                store=True, recursive=True)
    external_id = fields.Char('External ID', required=True)
    supplier_id = fields.Many2one('supplier.api.config', 'Supplier',
                                  required=True, ondelete='cascade')
    parent_id = fields.Many2one('supplier.api.category', 'Parent Category',
                                ondelete='cascade')
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many('supplier.api.category', 'parent_id', 'Child Categories')
    sync_enabled = fields.Boolean('Sync Enabled', default=False)
    product_count = fields.Integer('Product Count', default=0, readonly=True)

  
    synced_product_count = fields.Integer('Synced Products', default=0, readonly=True)

    odoo_category_id = fields.Many2one('product.category', 'Map to Odoo Category')
    public_category_id = fields.Many2one(
        'product.public.category',
        string='Website Category',
        help="Public category created automatically"
    )
    show_sale_price = fields.Boolean(
        'Show Sale Price for Products',
        default=True,
        help="If enabled, products imported from this category will have Sale Price = Cost + 30%."
    )
    product_ids = fields.One2many(
        'product.template',
        'supplier_api_category_id',
        string='Products'
    )

   
    synced_product_count_recursive = fields.Integer(
        string='Synced (incl. children)',
        compute='_compute_recursive_counts',
        store=False,
    )
    product_count_recursive = fields.Integer(
        string='Available (incl. children)',
        compute='_compute_recursive_counts',
        store=False,
    )


    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for category in self:
            if category.parent_id:
                category.complete_name = f"{category.parent_id.complete_name} / {category.name}"
            else:
                category.complete_name = category.name

    def _compute_recursive_counts(self):
        
        if not self:
            return

       
        self.env.cr.execute("""
            SELECT supplier_api_category_id, COUNT(*) AS cnt
            FROM product_template
            WHERE supplier_api_category_id IS NOT NULL
            GROUP BY supplier_api_category_id
        """)
        direct_counts = {row[0]: row[1] for row in self.env.cr.fetchall()}

        def get_descendant_ids(cat):
            """Retourne [cat.id] + tous IDs descendants (récursif)."""
            ids = [cat.id]
            for child in cat.child_ids:
                ids.extend(get_descendant_ids(child))
            return ids

        for cat in self:
            desc_ids = get_descendant_ids(cat)

            
            cats_in_scope = self.env['supplier.api.category'].browse(desc_ids)
            cat.product_count_recursive = sum(cats_in_scope.mapped('product_count'))

            
            cat.synced_product_count_recursive = sum(
                direct_counts.get(cid, 0) for cid in desc_ids
            )

  

    @api.model
    def _recompute_synced_counts(self, category_ids=None):
       
        if category_ids is not None:
        
            all_ids = set(category_ids)
            for cat in self.browse(category_ids):
                parent = cat.parent_id
                while parent:
                    all_ids.add(parent.id)
                    parent = parent.parent_id
            cats_to_update = self.browse(list(all_ids))
        else:
            cats_to_update = self.search([])

        if not cats_to_update:
            return

        ids_tuple = tuple(cats_to_update.ids) or (0,)

       
        self.env.cr.execute("""
            SELECT supplier_api_category_id, COUNT(*) as cnt
            FROM product_template
            WHERE supplier_api_category_id IN %s
            GROUP BY supplier_api_category_id
        """, (ids_tuple,))
        direct_counts = {row[0]: row[1] for row in self.env.cr.fetchall()}

        for cat in cats_to_update:
            count = direct_counts.get(cat.id, 0)
            new_vals = {
                'synced_product_count': count,
                'sync_enabled': count > 0,
            }
            cat.sudo().write(new_vals)

      
        for cat in cats_to_update:
            if not cat.sync_enabled and cat.parent_path:
                self.env.cr.execute("""
                    SELECT COUNT(*) FROM product_template pt
                    JOIN supplier_api_category sac ON sac.id = pt.supplier_api_category_id
                    WHERE sac.parent_path LIKE %s
                    AND sac.id != %s
                """, (cat.parent_path + '%', cat.id))
                desc_count = self.env.cr.fetchone()[0]
                if desc_count > 0:
                    cat.sudo().write({'sync_enabled': True})
                    _logger.info(
                        f"  sync_enabled=True (via descendants) : {cat.complete_name}"
                    )

    @api.model
    def _update_category_count(self, category_id):
        """Alias appelé après import d'un produit."""
        if category_id:
            self._recompute_synced_counts([category_id])

    def _compute_synced_products(self):
        """Alias de compatibilité."""
        self._recompute_synced_counts(self.ids)

    # ══════════════════════════════════════════════════════════════════════════
    # PUBLIC CATEGORY MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════════

    def _get_or_create_public_category(self):
        """
        Retourne le product.public.category correspondant à ce nœud,
        avec la bonne hiérarchie parente.
        """
        self.ensure_one()

        PublicCat = self.env['product.public.category']

        parent_pub_cat = None
        if self.parent_id:
            parent_pub_cat = self.parent_id._get_or_create_public_category()

        domain = [('name', '=', self.name)]
        if parent_pub_cat:
            domain.append(('parent_id', '=', parent_pub_cat.id))
        else:
            domain.append(('parent_id', '=', False))

        pub_cat = PublicCat.search(domain, limit=1)

        if not pub_cat:
            vals = {'name': self.name}
            if parent_pub_cat:
                vals['parent_id'] = parent_pub_cat.id
            pub_cat = PublicCat.sudo().create(vals)
            _logger.info(f"  Created public category: {pub_cat.complete_name}")
        else:
            expected_parent_id = parent_pub_cat.id if parent_pub_cat else False
            if pub_cat.parent_id.id != expected_parent_id:
                pub_cat.sudo().write({'parent_id': expected_parent_id})
                _logger.info(f"  Fixed parent for: {pub_cat.complete_name}")

        if self.public_category_id != pub_cat:
            self.sudo().write({'public_category_id': pub_cat.id})

        return pub_cat

    def _apply_public_category_to_products(self):
        self.ensure_one()

        public_cat = self._get_or_create_public_category()
        if not public_cat:
            _logger.warning(f"No public category for '{self.complete_name}', skipping.")
            return 0

        products = self.env['product.template'].search([
            ('supplier_api_category_id', '=', self.id)
        ])

        updated = 0
        for product in products:
       
            changed = product._sync_public_category(self)
            if changed:
                updated += 1

        _logger.info(f"'{self.complete_name}': {updated}/{len(products)} products updated.")
        return updated

    # ══════════════════════════════════════════════════════════════════════════
    # ACTIONS
    # ══════════════════════════════════════════════════════════════════════════

    def action_preview_products(self):
        self.ensure_one()
        if not self.supplier_id:
            raise UserError(_('No supplier API'))
        if self.supplier_id.api_type == 'tme':
            return self._preview_tme_products()
        raise UserError(_('Not implemented'))

    def _preview_tme_products(self):
        self.ensure_one()
        try:
            result = self.supplier_id._tme_api_call('/Products/GetSymbols', {
                'CategoryId': self.external_id
            })
            symbol_list = result.get('Data', {}).get('SymbolList', [])
            if not symbol_list:
                raise UserError(_('No products'))

            all_products_data = []
            for i in range(0, len(symbol_list), 50):
                batch = symbol_list[i:i + 50]
                batch_data = self.supplier_id._fetch_product_details_batch(batch)
                all_products_data.extend(batch_data)

            wizard = self.env['product.preview.wizard'].create({
                'category_id': self.id,
                'show_sale_price': self.show_sale_price,
            })

            Product = self.env['product.template']

            for product_data in all_products_data:
                symbol = product_data.get('symbol')
                barcode = product_data.get('barcode')
                exists = False
                odoo_product = None

                if barcode:
                    odoo_product = Product.search([('barcode', '=', barcode)], limit=1)
                    if odoo_product:
                        exists = True

                if not exists and symbol:
                    odoo_product = Product.search([('api_external_id', '=', symbol)], limit=1)
                    if odoo_product:
                        exists = True

                self.env['product.preview.wizard.line'].create({
                    'wizard_id': wizard.id,
                    'symbol': symbol,
                    'name': product_data.get('name', symbol),
                    'barcode': barcode if barcode else False,
                    'price': product_data.get('price', 0.0),
                    'currency': self.supplier_id.currency,
                    'stock_quantity': product_data.get('stock', 0),
                    'manufacturer': product_data.get('manufacturer', ''),
                    'photo_url': product_data.get('photo', ''),
                    'exists_in_odoo': exists,
                    'odoo_product_id': odoo_product.id if odoo_product else False,
                    'selected': not exists,
                })

            return {
                'name': _('Preview: %s (%d products)') % (self.name, len(all_products_data)),
                'type': 'ir.actions.act_window',
                'res_model': 'product.preview.wizard',
                'res_id': wizard.id,
                'view_mode': 'form',
                'target': 'new',
            }
        except Exception as e:
            _logger.error(f"Error: {str(e)}")
            raise UserError(_('Failed: %s') % str(e))

    def action_view_products(self):
        self.ensure_one()
        return {
            'name': _('Products: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'product.template',
            'view_mode': 'kanban,tree,form',
            'domain': [('supplier_api_category_id', '=', self.id)],
        }

    def action_sync_category_products(self):
        self.ensure_one()
        if not self.supplier_id:
            raise UserError(_('No supplier API'))

        _logger.info(f"SYNC CATEGORY: {self.name} | show_sale_price={self.show_sale_price}")

        try:
            if self.supplier_id.api_type == 'tme':
                result = self.supplier_id._tme_api_call('/Products/GetSymbols', {
                    'CategoryId': self.external_id
                })
                symbol_list = result.get('Data', {}).get('SymbolList', [])
                if not symbol_list:
                    raise UserError(_('No products found'))

                created_count = 0
                updated_count = 0

                for i in range(0, len(symbol_list), 50):
                    batch = symbol_list[i:i + 50]
                    try:
                        batch_created, batch_updated = self.supplier_id._tme_import_products_batch(
                            batch, self, show_sale_price=self.show_sale_price
                        )
                        created_count += len(batch_created)
                        updated_count += len(batch_updated)
                        self.env.cr.commit()
                    except Exception as batch_error:
                        _logger.error(f"Batch error: {str(batch_error)}")
                        self.env.cr.rollback()
                        continue

                self.env.cr.commit()

              
                self.env['supplier.api.category']._recompute_synced_counts([self.id])
                self.env.cr.commit()

                self._apply_public_category_to_products()

                total = created_count + updated_count
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Sync Complete!'),
                        'message': _(
                            'New products created: %d\n'
                            'Existing products updated: %d\n'
                            'Total synchronized: %d'
                        ) % (created_count, updated_count, total),
                        'type': 'success',
                        'sticky': True,
                    }
                }

        except Exception as e:
            _logger.error(f"SYNC FAILED: {str(e)}")
            self.env.cr.rollback()
            raise UserError(_('Sync failed: %s') % str(e))

    def action_download_csv(self):
        self.ensure_one()
        if not self.supplier_id:
            raise UserError(_('No supplier API configured'))
        if self.product_count == 0:
            raise UserError(_('No products in this category'))
        wizard = self.env['csv.choice.wizard'].create({'category_id': self.id})
        return {
            'name': _('CSV Options'),
            'type': 'ir.actions.act_window',
            'res_model': 'csv.choice.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _compute_synced_count_from_odoo(self):
        """
        Pour les catégories sans lien direct avec un produit Odoo :
        recherche par barcode/SKU via l'API, assigne supplier_api_category_id,
        puis recalcule les compteurs.
        """
        self.ensure_one()

       
        direct = self.env['product.template'].search_count([
            ('supplier_api_category_id', '=', self.id)
        ])
        if direct:
            self.env['supplier.api.category']._recompute_synced_counts([self.id])
            return direct

        try:
            result = self.supplier_id._tme_api_call('/Products/GetSymbols', {
                'CategoryId': self.external_id
            })
            api_symbols = result.get('Data', {}).get('SymbolList', [])

            if not api_symbols:
                self.sudo().write({'synced_product_count': 0, 'sync_enabled': False})
                return 0

            symbol_to_ean = {}
            for i in range(0, len(api_symbols), 50):
                batch = api_symbols[i:i+50]
                try:
                    params = {}
                    for j, sym in enumerate(batch):
                        params[f'SymbolList[{j:02d}]'] = sym
                    detail_result = self.supplier_id._tme_api_call('/Products/GetProducts', params)
                    for item in detail_result.get('Data', {}).get('ProductList', []):
                        sym = item.get('Symbol', '')
                        ean = item.get('EAN', '')
                        if sym:
                            symbol_to_ean[sym] = ean
                except Exception as e:
                    _logger.error(f"    GetProducts batch error: {str(e)}")
                    for sym in batch:
                        if sym not in symbol_to_ean:
                            symbol_to_ean[sym] = ''

            eans = [ean for ean in symbol_to_ean.values() if ean]
            skus = list(symbol_to_ean.keys())
            found_ids = set()

            if eans:
                by_barcode = self.env['product.template'].search([
                    ('supplier_id', '=', 'tme'), ('barcode', 'in', eans),
                ])
                found_ids.update(by_barcode.ids)

            if skus:
                by_sku = self.env['product.template'].search([
                    ('supplier_id', '=', 'tme'),
                    ('id', 'not in', list(found_ids)),
                    '|',
                    ('default_code', 'in', skus),
                    ('api_external_id', 'in', skus),
                ])
                found_ids.update(by_sku.ids)

            if found_ids:
                for product in self.env['product.template'].browse(list(found_ids)):
                    vals = {}
                    if not product.supplier_api_category_id:
                        vals['supplier_api_category_id'] = self.id
                    if not product.supplier_api_id:
                        vals['supplier_api_id'] = self.supplier_id.id
                    if vals:
                        product.sudo().write(vals)

            
            self.env['supplier.api.category']._recompute_synced_counts([self.id])

            _logger.info(f"  '{self.complete_name}': {len(found_ids)} products in Odoo")
            return len(found_ids)

        except Exception as e:
            _logger.error(f"  '{self.complete_name}': {str(e)}")
            self.sudo().write({'synced_product_count': 0})
            return 0

    def action_view_products_recursive(self):
        
        self.ensure_one()

    
        def get_all_descendant_ids(cat):
            ids = [cat.id]
            for child in cat.child_ids:
                ids.extend(get_all_descendant_ids(child))
            return ids

        all_cat_ids = get_all_descendant_ids(self)

        return {
            'name': _('Products: %s (incl. subcategories)') % self.complete_name,
            'type': 'ir.actions.act_window',
            'res_model': 'product.template',
            'view_mode': 'kanban,tree,form',
            'domain': [('supplier_api_category_id', 'in', all_cat_ids)],
        }        