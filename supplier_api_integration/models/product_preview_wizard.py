# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ProductPreviewWizard(models.TransientModel):
    _name = 'product.preview.wizard'
    _description = 'Preview Products from API'

    category_id = fields.Many2one('supplier.api.category', 'Category', required=True, readonly=True)
    supplier_id = fields.Many2one('supplier.api.config', 'Supplier', related='category_id.supplier_id', readonly=True)
    line_ids = fields.One2many('product.preview.wizard.line', 'wizard_id', 'Products')
    total_products = fields.Integer('Total Products', compute='_compute_stats')
    selected_products = fields.Integer('Selected Products', compute='_compute_stats')
    existing_products = fields.Integer('Already in Odoo', compute='_compute_stats')

    show_sale_price = fields.Boolean(
        'Enable Sale Price for Products',
        default=True,
        help="Changes apply immediately to existing products!"
    )

    @api.depends('line_ids', 'line_ids.selected', 'line_ids.exists_in_odoo')
    def _compute_stats(self):
        for wizard in self:
            wizard.total_products = len(wizard.line_ids)
            wizard.selected_products = len(wizard.line_ids.filtered('selected'))
            wizard.existing_products = len(wizard.line_ids.filtered('exists_in_odoo'))

    def action_select_all(self):
        self.line_ids.filtered(lambda l: not l.exists_in_odoo).write({'selected': True})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'product.preview.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'flags': {'mode': 'edit'},
        }

    def action_deselect_all(self):
        self.line_ids.write({'selected': False})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'product.preview.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'flags': {'mode': 'edit'},
        }

    # def write(self, vals):
    #     """Override write to detect show_sale_price changes"""
    #     result = super(ProductPreviewWizard, self).write(vals)

    #     if 'show_sale_price' in vals:
    #         for wizard in self:
    #             if wizard.category_id and wizard.existing_products > 0:
    #                 wizard._apply_pricing_immediately()

    #     return result
    def write(self, vals):
        """Override write to detect show_sale_price changes"""
        result = super(ProductPreviewWizard, self).write(vals)

        if 'show_sale_price' in vals:
            for wizard in self:
               
                wizard._apply_pricing_immediately()

        return result

    # def _apply_pricing_immediately(self):
    #     """Apply pricing changes IMMEDIATELY to existing products"""
    #     self.ensure_one()

    #     self.category_id.write({'show_sale_price': self.show_sale_price})

    #     Product = self.env['product.template']
    #     existing_products = Product.search([
    #         ('supplier_api_category_id', '=', self.category_id.id)
    #     ])

    #     if not existing_products:
    #         return

    #     updated_count = 0

    #     _logger.info("=" * 80)
    #     _logger.info(f"AUTO-UPDATE: {len(existing_products)} products")
    #     _logger.info(f"Toggle: {'ON' if self.show_sale_price else 'OFF'}")
    #     _logger.info("=" * 80)

    #     for product in existing_products:
    #         try:
    #             cost_price = product.standard_price

    #             if self.show_sale_price:
    #                 if cost_price > 0:
    #                     new_sale_price = cost_price * 1.3
    #                     product.sudo().write({'list_price': new_sale_price})
    #                     _logger.info(f"  {product.default_code}: {new_sale_price}")
    #                     updated_count += 1
    #             else:
    #                 product.sudo().write({'list_price': 0.0})
    #                 _logger.info(f"  {product.default_code}: 0")
    #                 updated_count += 1

    #             wizard_line = self.line_ids.filtered(
    #                 lambda l: l.exists_in_odoo and l.odoo_product_id == product and l.photo_url
    #             )

    #             if wizard_line and not product.image_url:
    #                 product.sudo().write({'image_url': wizard_line[0].photo_url})
    #                 _logger.info(f"  image_url set for {product.default_code}")

    #         except Exception as e:
    #             _logger.error(f"  Error: {str(e)}")
    #             continue

    #     self.env.cr.commit()
    #     _logger.info(f"Auto-updated {updated_count} products")
    
    def _apply_pricing_immediately(self):
        """Apply pricing changes IMMEDIATELY to existing products"""
        self.ensure_one()

        # Sauvegarder la valeur sur la catégorie
        self.category_id.write({'show_sale_price': self.show_sale_price})

       
        Product = self.env['product.template']
    
       
        existing_products = Product.search([
            ('supplier_api_category_id', '=', self.category_id.id)
        ])

        if not existing_products:
            return

        updated_count = 0

        _logger.info("=" * 80)
        _logger.info(f"AUTO-UPDATE: {len(existing_products)} products")
        _logger.info(f"Toggle: {'ON' if self.show_sale_price else 'OFF'}")
        _logger.info("=" * 80)

        for product in existing_products:
            try:
                cost_price = product.standard_price

                if self.show_sale_price:
                    if cost_price > 0:
                        new_sale_price = cost_price * 1.3
                        product.sudo().write({'list_price': new_sale_price})
                        _logger.info(f"  {product.default_code}: list_price = {new_sale_price}")
                        updated_count += 1
                else:
                    # ── CORRECTION : forcer list_price à 0 sans condition ──
                    product.sudo().write({'list_price': 0.0})
                    _logger.info(f"  {product.default_code}: list_price = 0.0")
                    updated_count += 1

                wizard_line = self.line_ids.filtered(
                    lambda l: l.exists_in_odoo and l.odoo_product_id == product and l.photo_url
                )

                if wizard_line and not product.image_url:
                    product.sudo().write({'image_url': wizard_line[0].photo_url})

            except Exception as e:
                _logger.error(f"  Error: {str(e)}")
                continue

        self.env.cr.commit()
        _logger.info(f"Auto-updated {updated_count} products")

    def _import_tme_products(self, symbols, show_sale_price=False):
        """Import TME products — returns (created_ids, updated_ids)"""
        if not symbols:
            return [], []

        created_ids = []
        updated_ids = []

        for i in range(0, len(symbols), 50):
            batch = symbols[i:i+50]
            try:
                batch_created, batch_updated = self.supplier_id._tme_import_products_batch(
                    batch,
                    self.category_id,
                    show_sale_price
                )
                if batch_created:
                    created_ids.extend(batch_created)
                if batch_updated:
                    updated_ids.extend(batch_updated)
                self.env.cr.commit()
            except Exception as e:
                _logger.error(f"Batch error: {str(e)}")
                self.env.cr.rollback()
                continue

        return created_ids, updated_ids

    def action_import_selected(self):
        """
        Import selected products with automatic stock synchronization.

        This method:
        1. Updates stock quants for all products (existing and new)
        2. Applies inventory to make changes effective
        3. Synchronizes supplier_stock_qty
        """
        self.ensure_one()

        selected_lines = self.line_ids.filtered('selected')
        existing_only = self.line_ids.filtered('exists_in_odoo')

        # ── CASE 1: No selection but all products already exist
        if not selected_lines and existing_only:
            _logger.info(f"Updating {len(existing_only)} existing products...")

            location_id = self.env['ir.config_parameter'].sudo().get_param(
                'config_supplier_csv_cronjob.stock_supplier_id'
            )

            if not location_id:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Configuration Error'),
                        'message': _('Supplier Warehouse location not configured!'),
                        'type': 'warning',
                    }
                }

            stock_id = int(location_id)

            for line in existing_only:
                if line.odoo_product_id:
                    try:
                        product = line.odoo_product_id
                        variant = product.product_variant_ids[:1]

                        if not variant:
                            _logger.warning(f"  No variant for {product.name}")
                            continue

                        qtyStock = self.env['stock.quant'].sudo().search([
                            ('location_id', '=', stock_id),
                            ('product_id', '=', variant.id),
                        ], limit=1)

                        if qtyStock:
                            qtyStock.sudo().write({'inventory_quantity': line.stock_quantity})
                            _logger.info(f"  Updated: {product.default_code} -> {line.stock_quantity}")
                        else:
                            qtyStock = self.env['stock.quant'].sudo().create({
                                'location_id': stock_id,
                                'product_id': variant.id,
                                'inventory_quantity': line.stock_quantity
                            })
                            _logger.info(f"  Created: {product.default_code} -> {line.stock_quantity}")

                        qtyStock.sudo().action_apply_inventory()
                        product.sudo().write({'supplier_stock_qty': line.stock_quantity})

                    except Exception as e:
                        _logger.error(f"  Error for {line.odoo_product_id.name}: {str(e)}")
                        continue

            self.env.cr.commit()

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Already Imported'),
                    'message': _(
                        'All %d products are already imported!\n'
                        'Stock synchronized from API.'
                    ) % len(existing_only),
                    'type': 'info',
                    'sticky': False,
                }
            }

        # ── CASE 2: Nothing selected
        if not selected_lines:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Selection'),
                    'message': _('Please select at least one product to import!'),
                    'type': 'warning',
                }
            }

        # ── CASE 3: Normal import of selected products
        self.category_id.write({'show_sale_price': self.show_sale_price})

        _logger.info("=" * 80)
        _logger.info(f"IMPORT: {len(selected_lines)} products")
        _logger.info(f"Show Sale Price: {self.show_sale_price}")
        _logger.info("=" * 80)

        symbols = selected_lines.mapped('symbol')
        imported_ids = []
        updated_ids = []

        try:
            if self.supplier_id.api_type == 'tme':
                imported_ids, updated_ids = self._import_tme_products(
                    symbols, self.show_sale_price
                )

            all_processed_ids = imported_ids + updated_ids

            if all_processed_ids:
                Product = self.env['product.template']

                location_id = self.env['ir.config_parameter'].sudo().get_param(
                    'config_supplier_csv_cronjob.stock_supplier_id'
                )

                if not location_id:
                    _logger.warning("Supplier Warehouse not configured, skipping stock sync")
                else:
                    stock_id = int(location_id)

                    for line in selected_lines:
                        product = Product.search([
                            '|',
                            ('barcode', '=', line.barcode),
                            ('api_external_id', '=', line.symbol)
                        ], limit=1)

                        if product:
                            try:
                                variant = product.product_variant_ids[:1]

                                if variant:
                                    qtyStock = self.env['stock.quant'].sudo().search([
                                        ('location_id', '=', stock_id),
                                        ('product_id', '=', variant.id),
                                    ], limit=1)

                                    if qtyStock:
                                        qtyStock.sudo().write({
                                            'inventory_quantity': line.stock_quantity
                                        })
                                    else:
                                        qtyStock = self.env['stock.quant'].sudo().create({
                                            'location_id': stock_id,
                                            'product_id': variant.id,
                                            'inventory_quantity': line.stock_quantity
                                        })

                                    qtyStock.sudo().action_apply_inventory()
                                    product.sudo().write({'supplier_stock_qty': line.stock_quantity})
                                    _logger.info(
                                        f"  Stock synchronized: {product.default_code} "
                                        f"= {line.stock_quantity} units"
                                    )

                            except Exception as e:
                                _logger.error(f"  Stock sync error for {product.name}: {str(e)}")

                            if line.photo_url and not product.image_url:
                                product.sudo().write({'image_url': line.photo_url})
                                _logger.info(f"  image_url set for {product.default_code}")

                            line.sudo().write({
                                'exists_in_odoo': True,
                                'odoo_product_id': product.id,
                                'selected': False
                            })

            self.env.cr.commit()

            # Recalculate synced_product_count for all categories
            self.env['supplier.api.category']._recompute_synced_counts(
                [self.category_id.id]
            )
            self.env.cr.commit()

            self.supplier_id.invalidate_cache(['synced_products', 'products_without_category'])

            total = len(imported_ids) + len(updated_ids)

            _logger.info("=" * 80)
            _logger.info(f"COMPLETE:")
            _logger.info(f"   New products created      : {len(imported_ids)}")
            _logger.info(f"   Existing products updated : {len(updated_ids)}")
            _logger.info(f"   Total synchronized        : {total}")
            _logger.info("=" * 80)

            if imported_ids:
                return {
                    'type': 'ir.actions.act_window',
                    'name': _('New Products Imported (%d)') % len(imported_ids),
                    'res_model': 'product.template',
                    'view_mode': 'kanban,tree,form',
                    'domain': [('id', 'in', imported_ids)],
                    'context': {'search_default_from_api': 1},
                    'target': 'current',
                }
            elif updated_ids:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Sync Complete!'),
                        'message': _(
                            'No new products.\n'
                            '%d existing products updated.'
                        ) % len(updated_ids),
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Nothing to do'),
                        'message': _('No products were created or updated.'),
                        'type': 'info',
                    }
                }

        except Exception as e:
            _logger.error(f"FAILED: {str(e)}", exc_info=True)
            self.env.cr.rollback()
            raise UserError(_('Import failed: %s') % str(e))


class ProductPreviewWizardLine(models.TransientModel):
    _name = 'product.preview.wizard.line'
    _description = 'Product Preview Line'
    _order = 'exists_in_odoo, name'

    wizard_id = fields.Many2one('product.preview.wizard', 'Wizard', required=True, ondelete='cascade')
    symbol = fields.Char('Symbol', required=True)
    name = fields.Char('Product Name', required=True)
    barcode = fields.Char('Barcode/EAN')
    price = fields.Float('Cost Price')
    sale_price = fields.Float('Sale Price (Preview)', compute='_compute_sale_price', store=False)
    currency = fields.Char('Currency', default='EUR')
    stock_quantity = fields.Integer('Stock')
    manufacturer = fields.Char('Manufacturer')
    photo_url = fields.Char('Photo URL')
    image_preview = fields.Binary('Image', compute='_compute_image_preview')
    exists_in_odoo = fields.Boolean('Already in Odoo', default=False)
    odoo_product_id = fields.Many2one('product.template', 'Odoo Product')
    selected = fields.Boolean('Select', default=False)

    @api.depends('price', 'wizard_id.show_sale_price')
    def _compute_sale_price(self):
        for line in self:
            if line.wizard_id and line.wizard_id.show_sale_price:
                line.sale_price = line.price * 1.3
            else:
                line.sale_price = 0.0

    @api.depends('photo_url')
    def _compute_image_preview(self):
        for line in self:
            if not line.photo_url:
                line.image_preview = False
                continue

            try:
                supplier = line.wizard_id.supplier_id
                image_data = supplier._download_and_validate_image(line.photo_url)
                line.image_preview = image_data if image_data else False
            except Exception as e:
                _logger.error(f"Error loading preview: {str(e)}")
                line.image_preview = False

    def action_open_product(self):
        """Open the existing product in Odoo"""
        self.ensure_one()

        if not self.odoo_product_id:
            return False

        return {
            'name': _('Product: %s') % self.odoo_product_id.name,
            'type': 'ir.actions.act_window',
            'res_model': 'product.template',
            'res_id': self.odoo_product_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.onchange('selected')
    def _onchange_selected(self):
        """Prevent selection of already imported products"""
        if self.selected and self.exists_in_odoo:
            self.selected = False
            return {
                'warning': {
                    'title': _('Already Imported'),
                    'message': _('This product already exists in Odoo.\n\n'
                                 'Product: %s\n'
                                 'Use "Open Product" button to view it.') % self.name
                }
            }