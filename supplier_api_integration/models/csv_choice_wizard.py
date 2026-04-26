# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import csv
import io
import base64
import logging

_logger = logging.getLogger(__name__)


class CsvChoiceWizard(models.TransientModel):
    _name = 'csv.choice.wizard'
    _description = 'CSV Choice: View or Download'

    category_id = fields.Many2one('supplier.api.category', 'Category', required=True, readonly=True)
    category_name = fields.Char('Category', related='category_id.complete_name', readonly=True)
    product_count = fields.Integer('Products', related='category_id.product_count', readonly=True)

    csv_data = fields.Binary('CSV Data', readonly=True)
    csv_filename = fields.Char('Filename', readonly=True)

    csv_viewer_url = fields.Char('Viewer URL', compute='_compute_csv_viewer_url')

    @api.depends('category_id')
    def _compute_csv_viewer_url(self):
        """Generate the live viewer URL"""
        base_url = 'http://localhost:8069'

        for wizard in self:
            if wizard.category_id:
                wizard.csv_viewer_url = f"{base_url}/csv/view/{wizard.category_id.id}"
            else:
                wizard.csv_viewer_url = False

    @api.model
    def create(self, vals):
        """Generate the CSV immediately on wizard creation"""
        wizard = super(CsvChoiceWizard, self).create(vals)
        wizard._generate_csv()
        return wizard

    def _generate_csv(self):
        """Generate the CSV file once (for download)"""
        self.ensure_one()

        category = self.category_id
        supplier = category.supplier_id

        try:
            result = supplier._tme_api_call('/Products/GetSymbols', {
                'CategoryId': category.external_id
            })

            symbol_list = result.get('Data', {}).get('SymbolList', [])

            if not symbol_list:
                raise UserError(_('No products found'))

            all_products = []
            for i in range(0, len(symbol_list), 50):
                batch = symbol_list[i:i+50]
                products_data = supplier._fetch_product_details_batch(batch)
                all_products.extend(products_data)

            output = io.StringIO()
            writer = csv.writer(output)

            writer.writerow([
                'Symbol', 'Description', 'Manufacturer', 'EAN/Barcode',
                'Stock Quantity', 'Cost Price', 'Sale Price', 'Currency',
                'Category', 'Weight (kg)', 'Photo URL', 'In Odoo'
            ])

            for product in all_products:
                exists = self.env['product.template'].search_count([
                    '|',
                    ('barcode', '=', product.get('barcode')),
                    ('api_external_id', '=', product.get('symbol'))
                ]) > 0

                cost = product.get('price', 0.0)
                sale = (cost * 1.3) if category.show_sale_price else 0.0

                writer.writerow([
                    product.get('symbol', ''),
                    product.get('name', ''),
                    product.get('manufacturer', ''),
                    product.get('barcode', ''),
                    product.get('stock', 0),
                    f"{cost:.2f}",
                    f"{sale:.2f}",
                    product.get('currency', supplier.currency),
                    category.complete_name,
                    f"{product.get('weight', 0.0):.3f}",
                    product.get('photo', ''),
                    'Yes' if exists else 'No'
                ])

            csv_content = output.getvalue().encode('utf-8')
            output.close()

            self.csv_data = base64.b64encode(csv_content)
            self.csv_filename = f"{category.name.replace('/', '-')}_{fields.Date.today()}.csv"

        except Exception as e:
            raise UserError(_('Failed to generate CSV: %s') % str(e))

    def action_view_online(self):
        """Open the Live CSV Viewer (always up to date)"""
        self.ensure_one()

        if not self.csv_viewer_url:
            raise UserError(_('Viewer URL not available'))

        _logger.info(f"Opening CSV Viewer: {self.csv_viewer_url}")

        return {
            'type': 'ir.actions.act_url',
            'url': self.csv_viewer_url,
            'target': 'new',
        }

    def action_download(self):
        """Download the CSV file"""
        self.ensure_one()

        if not self.csv_data:
            raise UserError(_('CSV not generated'))

        attachment = self.env['ir.attachment'].create({
            'name': self.csv_filename,
            'type': 'binary',
            'datas': self.csv_data,
            'mimetype': 'text/csv',
            'res_model': self._name,
            'res_id': self.id,
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }