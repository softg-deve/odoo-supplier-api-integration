# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class SupplierStockInfoWizard(models.TransientModel):
    """
    Wizard to display supplier stock information.
    Replaces the quants view (which was creating physical stock lines).
    """
    _name = 'supplier.stock.info.wizard'
    _description = 'Supplier Stock Information'

    product_id = fields.Many2one('product.template', 'Product', required=True, readonly=True)
    product_name = fields.Char('Product Name', related='product_id.name', readonly=True)
    supplier_stock_qty = fields.Integer('Supplier Stock', readonly=True)

    supplier_info_ids = fields.Many2many(
        'product.supplierinfo',
        compute='_compute_supplier_info_ids',
        string='Supplier Details'
    )

    @api.depends('product_id')
    def _compute_supplier_info_ids(self):
        """Load supplier info lines with available stock"""
        for wizard in self:
            if wizard.product_id:
                wizard.supplier_info_ids = wizard.product_id.seller_ids.filtered(
                    lambda s: s.api_stock_quantity > 0
                )
            else:
                wizard.supplier_info_ids = False