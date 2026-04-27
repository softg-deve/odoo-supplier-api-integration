# -*- coding: utf-8 -*-
{
    'name': 'Supplier API Integration',
    'version': '2.3.2',
    'category': 'Inventory',
    'summary': 'Import and synchronize products from supplier APIs (TME Electronics)',
    'description': """
Supplier API Integration
========================

This module connects Odoo to external supplier APIs (currently TME Electronics)
and automates the full product lifecycle from import to website publication.

Key Features
------------
- Fetch and browse supplier product categories with live product counts
- Preview products before importing with stock, price and image data
- Import selected products with automatic duplicate detection (barcode/SKU)
- Hourly cron: sync stock and prices for all imported products
- Daily cron: full mirror sync (categories, products, removed items)
- Auto-publish products on the website when stock is available
- Auto-assign website public categories based on supplier category hierarchy
- Export category products to CSV or view them in a live browser viewer
- theme_prime integration (optional): auto-apply labels and product settings
- Migration script included for upgrading to v2.3.2

Requirements
------------
- Odoo 16.0+
- Python: requests, Pillow
- website_sale module
    """,
    'author': 'Soft G Co. Ltd',
    'website': 'https://softg.dev',
    'license': 'OPL-1',
    'support': 'support@softg.dev',
    'depends': [
        'base',
        'product',
        'purchase',
        'stock',
        'website_sale',
    ],
    'data': [
        # Security
        'security/ir.model.access.csv',
        # Data
        'data/ir_cron.xml',
        # Views
        'views/supplier_api_views.xml',
        'views/product_template_views.xml',
        'views/product_preview_wizard_views.xml',
        'views/csv_choice_wizard_views.xml',
        'views/csv_viewer_live_templates.xml',
        'views/stock_quant.xml',
        'views/views_supplier_stock_wizard.xml',
        # Menu
        'views/menu_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
    'external_dependencies': {
        'python': ['requests', 'Pillow'],
    },
    'images': ['static/description/banner.png'],
    'post_init_hook': 'post_init_hook',
    'pre_uninstall_hook': 'pre_uninstall_hook',
    'price': 249.00,
    'currency': 'EUR',
}