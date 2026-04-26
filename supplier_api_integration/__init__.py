from . import models
from . import controllers

# -*- coding: utf-8 -*-
import logging
_logger = logging.getLogger(__name__)


def _clean_duplicate_supplier_info(env, supplier, cr):
    """
    Keep ONLY the supplier info line for the current partner.
    Delete all lines belonging to old/duplicate partners.
    """
    _logger.info(f"    Cleaning duplicate supplier info: {supplier.name}")

    partner = env['res.partner'].search([
        ('name', '=', supplier.name),
        ('supplier_rank', '>', 0),
    ], limit=1)

    if not partner:
        _logger.info(f"    No partner found for {supplier.name}, skipping")
        return

    products = env['product.template'].search([
        ('supplier_id', '=', supplier.api_type),
    ])

    cleaned = 0
    for product in products:
        all_info = env['product.supplierinfo'].search([
            ('product_tmpl_id', '=', product.id),
        ])

        to_delete = all_info.filtered(
            lambda s: s.partner_id.id != partner.id
        )

        if to_delete:
            to_delete.sudo().unlink()
            cleaned += len(to_delete)

    if cleaned > 0:
        cr.commit()
        _logger.info(f"    Removed {cleaned} duplicate supplier info lines")
    else:
        _logger.info(f"    No duplicates found")


def post_init_hook(cr, registry):
    """
    Fix public_categ_ids, supplier_id, and duplicate supplier_info
    on module installation or upgrade.
    """
    _logger.info("[post_init_hook] START")

    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    try:
       
        products_via_api_id = env['product.template'].search([
            ('supplier_api_id', '!=', False),
            ('supplier_id', 'not in', ['tme']),
        ])
        if products_via_api_id:
            products_via_api_id.sudo().write({'supplier_id': 'tme'})
            cr.commit()
            _logger.info(f"  [A] Fixed supplier_id for {len(products_via_api_id)} products")

        suppliers = env['supplier.api.config'].search([('active', '=', True)])
        if not suppliers:
            _logger.info("  No active suppliers, skipping category fix.")
            _logger.info("[post_init_hook] Done")
            return

        for supplier in suppliers:
            _logger.info(f"  Processing: {supplier.name}")

           
            products_this_supplier = env['product.template'].search([
                ('supplier_api_id', '=', supplier.id),
                ('supplier_id', '!=', supplier.api_type),
            ])
            if products_this_supplier:
                products_this_supplier.sudo().write({'supplier_id': supplier.api_type})
                cr.commit()
                _logger.info(
                    f"    supplier_id='{supplier.api_type}' fixed "
                    f"for {len(products_this_supplier)} products"
                )

            # Clean duplicate supplier info lines
            _clean_duplicate_supplier_info(env, supplier, cr)

            # Rebuild public category hierarchy
            all_cats = env['supplier.api.category'].search(
                [('supplier_id', '=', supplier.id)], order='parent_path'
            )
            if not all_cats:
                _logger.info(f"    No categories found, skipping.")
                continue

            for cat in all_cats:
                try:
                    cat._get_or_create_public_category()
                except Exception as e:
                    _logger.error(f"    {cat.complete_name}: {str(e)}")
            cr.commit()
            _logger.info(f"    Public category hierarchy rebuilt")

            # Fix public_categ_ids for all products of this supplier
            products = env['product.template'].search([
                '|',
                ('supplier_api_id', '=', supplier.id),
                ('supplier_id', '=', supplier.api_type),
                ('supplier_api_category_id', '!=', False),
            ])

            fixed = 0
            for i, product in enumerate(products, 1):
                try:
                    api_cat = product.supplier_api_category_id
                    pub_cat = (
                        api_cat.public_category_id
                        or api_cat._get_or_create_public_category()
                    )
                    # if pub_cat and product.public_categ_ids.ids != [pub_cat.id]:
                    #     product.sudo().write({
                    #         'public_categ_ids': [(6, 0, [pub_cat.id])]
                    #     })
                    # ✅ CORRECT
                    if pub_cat:
                        product._sync_public_category(api_cat)    
                        fixed += 1
                    if i % 100 == 0:
                        cr.commit()
                except Exception as e:
                    _logger.error(f"    {product.default_code}: {str(e)}")

            cr.commit()
            _logger.info(f"    public_categ_ids: {fixed}/{len(products)} fixed")

        _logger.info("[post_init_hook] Done")

    except Exception as e:
        _logger.error(f"[post_init_hook] Failed: {str(e)}", exc_info=True)


def pre_uninstall_hook(cr, registry):
    _logger.info("[pre_uninstall_hook] Running...")