# -*- coding: utf-8 -*-
from odoo import api, models, fields
import logging

_logger = logging.getLogger(__name__)


class ProductTemplateThemeAuto(models.Model):
    """
    Automatic integration with theme_prime.
    Activates ONLY if theme_prime is installed.
    """
    _inherit = 'product.template'

    def _is_theme_prime_installed(self):
        """Check if theme_prime is installed"""
        return self.env['ir.module.module'].search([
            ('name', '=', 'theme_prime'),
            ('state', '=', 'installed')
        ], limit=1)

    @api.model
    def create(self, vals):
        """Override create to automatically apply theme configuration"""
        product = super(ProductTemplateThemeAuto, self).create(vals)
        
        if product.supplier_api_id and self._is_theme_prime_installed():
            product._apply_theme_prime_features()
        
        return product

    def write(self, vals):
        result = super(ProductTemplateThemeAuto, self).write(vals)

        if 'is_published' in vals and vals['is_published']:
            for product in self:
                if product.supplier_api_id and self._is_theme_prime_installed():
                    product._apply_theme_prime_features()

        return result

    def _apply_theme_prime_features(self):
        """
        Automatically apply theme_prime features.

        This method does NOT modify any XML/templates because:
        - theme_prime already handles ALL templates via inheritance
        - _config_product_item and _config_shop_layout configs are already active
        - We only need to ensure the FIELDS are correctly set
        """
        self.ensure_one()
        
        try:
            updates = {}

            if not self.website_published and self.is_published:
                updates['website_published'] = True

            if not self.sale_ok:
                updates['sale_ok'] = True

            if not self.dr_label_id:
                Label = self.env['dr.product.label']

                if self.create_date:
                    days_old = (fields.Datetime.now() - self.create_date).days
                    if days_old < 7:
                        new_label = Label.search([('name', 'ilike', 'new')], limit=1)
                        if new_label:
                            updates['dr_label_id'] = new_label.id

                if not updates.get('dr_label_id') and self.qty_available > 0:
                    stock_label = Label.search([('name', 'ilike', 'stock')], limit=1)
                    if stock_label:
                        updates['dr_label_id'] = stock_label.id

            if updates:
                self.sudo().write(updates)
                _logger.info(f"Theme features applied: {self.name}")

        except Exception as e:
            _logger.warning(f"Theme features not fully applied: {str(e)}")


class SupplierApiConfigThemeAuto(models.Model):
    """
    Extension of supplier.api.config to handle theme configuration.
    """
    _inherit = 'supplier.api.config'

    apply_theme_config = fields.Boolean(
        'Apply Theme Configuration',
        default=True,
        help="Automatically apply theme_prime features to imported products (if installed)"
    )

    default_product_label_id = fields.Many2one(
        'dr.product.label',
        string='Default Product Label',
        help="Label to apply to all imported products from this supplier (requires theme_prime)"
    )

    def _create_new_product(self, product_data, partner, category, public_category=None, show_sale_price=False):
        """
        Override to apply theme configuration on product creation.
        """
        product_id = super(SupplierApiConfigThemeAuto, self)._create_new_product(
            product_data, partner, category, public_category, show_sale_price
        )

        if not product_id:
            return False

        if self.apply_theme_config:
            product = self.env['product.template'].browse(product_id)

            if product._is_theme_prime_installed():

                if self.default_product_label_id and not product.dr_label_id:
                    product.sudo().write({'dr_label_id': self.default_product_label_id.id})

                product._apply_theme_prime_features()
            else:
                _logger.debug("theme_prime not installed, skipping theme features")

        return product_id

    def _update_existing_product(self, product, product_data, partner, category, public_category=None, show_sale_price=False):
        """
        Override to maintain theme configuration on product update.
        """
        super(SupplierApiConfigThemeAuto, self)._update_existing_product(
            product, product_data, partner, category, public_category, show_sale_price
        )

        if self.apply_theme_config and product._is_theme_prime_installed():
            product._apply_theme_prime_features()