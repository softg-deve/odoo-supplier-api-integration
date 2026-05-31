# migration/2.3.2/fix_public_categ_ids.py

import logging
_logger = logging.getLogger(__name__)

def migrate(cr, version):
    _logger.info("=" * 70)
    _logger.info("[MIGRATION 2.3.2] Fix public_categ_ids multi-category support")
    _logger.info("=" * 70)

    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    try:
      
        _logger.info("STEP 1: Rebuilding public_category_id hierarchy...")
        all_api_cats = env['supplier.api.category'].search(
            [], order='parent_path'
        )
        _logger.info(f"   {len(all_api_cats)} categories found")

        hier_ok = 0
        hier_err = 0
        for cat in all_api_cats:
            try:
                pub = cat._get_or_create_public_category()
                if pub:
                    hier_ok += 1
                    _logger.info(f"   OK: '{cat.complete_name}' -> '{pub.complete_name}'")
                else:
                    hier_err += 1
                    _logger.warning(f"   EMPTY: '{cat.complete_name}'")
            except Exception as e:
                hier_err += 1
                _logger.warning(f"   ERROR '{cat.complete_name}': {str(e)}")

        cr.commit()
        _logger.info(f"   Hierarchy: {hier_ok} OK, {hier_err} errors")

     
        _logger.info("STEP 2: Fixing public_categ_ids for multi-category products...")
        
       
        cr.execute("""
            SELECT DISTINCT pt.id, pt.default_code, pt.supplier_api_category_id
            FROM product_template pt
            WHERE pt.supplier_api_category_id IS NOT NULL
            AND pt.supplier_api_id IS NOT NULL
        """)
        
        products_data = cr.fetchall()
        _logger.info(f"   {len(products_data)} products to process")

        fixed = 0
        multi_cat_products = 0
        
        for product_id, default_code, current_cat_id in products_data:
            try:
                product = env['product.template'].browse(product_id)
                current_cat = env['supplier.api.category'].browse(current_cat_id)
                
                if not current_cat:
                    continue
                    
                pub_cat = current_cat.public_category_id
                if not pub_cat:
                    pub_cat = current_cat._get_or_create_public_category()
                
                if not pub_cat:
                    continue
                
              
                current_ids = product.public_categ_ids.ids
                
                if pub_cat.id not in current_ids:
                    new_ids = list(current_ids) + [pub_cat.id]
                    product.sudo().write({'public_categ_ids': [(6, 0, new_ids)]})
                    fixed += 1
                    if len(new_ids) > 1:
                        multi_cat_products += 1
                    _logger.info(
                        f"   FIXED: {default_code} "
                        f"added '{pub_cat.complete_name}' "
                        f"(now in {len(new_ids)} categories)"
                    )
                
                if product_id % 50 == 0:
                    cr.commit()
                    _logger.info(f"   ... {product_id}/{len(products_data)}")
                    
            except Exception as e:
                _logger.error(f"   ERROR {default_code}: {str(e)}")
                continue

        cr.commit()

        _logger.info("=" * 70)
        _logger.info("MIGRATION 2.3.2 COMPLETE")
        _logger.info(f"   Products fixed           : {fixed}")
        _logger.info(f"   Multi-category products  : {multi_cat_products}")
        _logger.info(f"   Hierarchy OK/ERR         : {hier_ok}/{hier_err}")
        _logger.info("=" * 70)

    except Exception as e:
        _logger.error(f"MIGRATION 2.3.2 FAILED: {str(e)}", exc_info=True)
        cr.rollback()
        raise