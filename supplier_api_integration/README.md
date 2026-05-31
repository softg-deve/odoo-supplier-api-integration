# Supplier API Integration for Odoo

**Version:** 2.3.2  
**Compatibility:** Odoo 16.0+  
**License:** OPL-1  
**Author:** Soft G Co. Ltd  
**Website:** https://softg.dev  

---

## Overview

Automate your entire product catalog synchronization with external supplier APIs. 

**Supplier API Integration** connects Odoo to TME Electronics (and any configurable supplier API) to keep your inventory, pricing, website categories, and product data perfectly synchronized — with zero manual intervention.

Import thousands of products in minutes, keep stock and prices updated hourly, and let your website automatically publish or hide products based on real-time supplier availability.

---

## Why This Module?

### ⏰ Real-time Synchronization
- **Hourly:** Stock quantities and prices refresh automatically
- **Daily:** Full catalog sync, category updates, and removed product detection
- **Always current:** No spreadsheets. No manual updates. No guessing.

### 🎯 Smart Anti-Duplicate Engine
- Searches by barcode first, then SKU
- Existing products are updated, never duplicated
- Three matching rules cover every edge case
- Restores missing API links automatically

### 🚀 Zero Manual Work
- Import categories and products with one click
- Preview images, stock, and prices before importing
- Auto-map supplier categories to website categories
- Auto-publish/unpublish based on stock availability

### 📊 Live CSV Viewer
- Browse any category as a live spreadsheet
- Search, sort, and filter in the browser
- Auto-refresh every 30 seconds
- Export visible rows to CSV anytime

### 🌐 B2B Ready
- Track warehouse stock AND supplier stock separately
- Show customers both in-stock and remote availability
- Support back-orders with "Continue Selling" flag
- Multi-source delivery messages (1-2 days vs 4-8 days)

### 🔧 Built for Any API
- TME Electronics bundled and production-ready
- Extensible architecture for Mouser, Digi-Key, RS, Farnell, etc.
- Custom connector development available on request

---

## Key Features

### 📁 Category Management

Browse the complete supplier category tree with:
- Live product count (available at supplier vs. imported in Odoo)
- One-toggle sync enable/disable per category
- Automatic mapping to Odoo internal and website categories
- Recursive counts including all subcategories
- Search across category names, product names, SKUs, and barcodes

### 👁️ Product Preview Wizard

Before importing, see:
- Product thumbnails loaded live from supplier
- Stock quantities and cost prices
- Which products already exist in Odoo (badged)
- Sale price toggle (cost × 1.3 markup)
- Bulk "Select All New" for quick import

### 🔄 Automatic Synchronization

**Hourly Cron (Every Hour)**
- Stock quantities updated
- Cost prices refreshed
- Product names synchronized
- Manufacturer, barcode, weight, images updated
- Website categories auto-assigned
- Products auto-published (stock > 0) or unpublished (stock = 0)

**Daily Cron (2 AM)**
- Complete category tree re-sync
- All product fields refreshed
- Detects products removed from supplier (auto-unpublish + notification)
- Counters recalculated
- Missing images downloaded
- Broken category paths repaired

### 📦 Product Management

Every imported product includes:
- SKU (default code) from supplier
- EAN barcode (global deduplication)
- Product name, manufacturer, weight
- Live image URL + auto-downloaded image
- Cost price and optional sale price (configurable per category)
- Supplier warehouse stock (separate from physical warehouse)
- Website categories (auto-assigned from supplier hierarchy)
- API sync timestamp
- Manual sync button for on-demand refresh

### 📊 CSV Export & Live Viewer

Two-step workflow:
1. Click **CSV** on any category
2. Choose:
   - **View Online:** Live spreadsheet with search, sort, auto-refresh (30 sec)
   - **Download:** Static CSV snapshot

Features:
- Instant search by symbol, name, manufacturer, barcode
- Click any column header to sort
- Auto-refresh countdown timer
- "In Odoo" badge on imported products
- Export visible rows as CSV

### 🛒 Website Integration

Auto-configures products for your Odoo website:
- Website categories assigned from supplier hierarchy
- Auto-publish when stock available
- Auto-unpublish when out of stock
- Mixed inventory messages:
  - Warehouse stock: "In stock · Ship 1-2 days"
  - Supplier stock: "Available remotely · Ship 4-8 days"
- Back-order support with "Continue Selling" flag
- Theme Prime compatibility (optional)

### 🎨 Theme Prime Integration (Optional)

If your store runs Theme Prime:
- Products automatically labeled ("New", "In Stock", etc.)
- Theme-specific configuration applied
- Product fields pre-configured
- Zero manual cleanup

---

## Installation & Setup

### 1. Install the Module

- Go to **Apps** → Search "Supplier API Integration"
- Click **Install**

### 2. Configure API Credentials

- Go to **Inventory > Configuration > Suppliers API > API TME**
- Enter:
  - **API Token:** From your TME account dashboard
  - **App Secret:** From your TME account dashboard
  - **Country:** Your country code (default: GB)
  - **Language:** Your language (default: EN)
  - **Currency:** Your currency (default: EUR)

### 3. Test Connection

- Click **Test Connection** button
- Confirm credentials are valid

### 4. Fetch Supplier Categories

- Click **Fetch Categories** button
- Wait for the category tree to load
- The entire TME supplier hierarchy is now available in Odoo

### 5. Import Products

- Browse categories tree
- Click **Preview** to see products in advance
- Click **CSV** to view or export a category
- Click **Import** to bring products into Odoo
- Sit back — hourly and daily crons handle the rest

---

## How It Works

### Product Matching (Anti-Duplicate Logic)

When importing a product:

1. **Search by Barcode (EAN)** — Global search
   - If found → **Update** existing product
   - If not found → Continue to step 2

2. **Search by SKU** — Default code or API external ID
   - If found → **Update** existing product
   - If not found → **Create** new product

**Result:** Zero duplicates. Existing products updated, new products created.

### Auto-Publishing Logic

**Stock > 0** → Product automatically published on website  
**Stock = 0** → Product automatically unpublished (hidden)

Respects "Continue Selling" override:
- If enabled: products stay visible even at zero stock (for pre-orders)
- If disabled: products auto-hide when out of stock

### Mixed Inventory Display

Customers see both your warehouse AND supplier stock:
Scenario 1: Warehouse 4 units + Supplier 7 units
→ "4 in stock (1-2 days)" + "7 available remotely (4-8 days)"
Scenario 2: Warehouse 0 + Supplier 7 + Continue Selling enabled
→ "7 available remotely (4-8 days)" + "Back-order (3 weeks)"

---

## Stock Locations

The module automatically creates:

**Supplier Warehouse** (Internal Location)
- Stores virtual inventory from supplier API
- Used for forecasted stock calculations
- Separate from your physical warehouse
- Read-only (updated by crons, not manually)

---

## Cron Jobs

### Hourly: Update Stock & Prices
Runs: Every hour
Action: Batch update stock, prices, images for all imported products
Timeout: 60 seconds

**Updated fields:**
- `stock_qty` (supplier warehouse)
- `cost_price`
- `list_price` (if sale price enabled)
- `name`, `manufacturer`, `barcode`, `weight`
- `image_url`, `image_1920`
- `is_published` (auto-publish/unpublish)
- `api_last_sync` timestamp

### Daily: Full Mirror Sync
Runs: Every day at 2 AM
Action: Complete category tree sync + full product refresh
Timeout: 120 seconds (may take longer)

**Updated elements:**
- Category tree (new categories, renames)
- Product counts per category
- All product fields (including metadata)
- Detects removed products (auto-unpublish + notification)
- Repairs broken category hierarchies
- Recalculates counters
- Fixes missing images

---

## Configuration Options

### Category Settings

**Sync Enabled**
- Toggle on/off synchronization for a specific category
- When disabled: no new imports, crons skip this category
- Already-imported products still update via hourly cron

**Show Sale Price**
- Enable: products get list_price = cost_price × 1.3
- Disable: list_price set to 0 (quote-on-request)
- Change applies retroactively to entire category

**Odoo Category Mapping**
- Map supplier category to your internal Odoo product category
- Used for internal organization, not website display

**Website Category Mapping**
- Map supplier category to Odoo public.category
- Determines where product appears on website
- Auto-created if not manually assigned

### Global Settings

**Auto Synchronization**
- Enable: cron jobs run automatically
- Disable: crons skip this supplier (manual refresh only)

**Active**
- Toggle to temporarily disable a supplier without deleting configuration

---

## Advanced Features

### Product Deduplication

The module tracks:
- `barcode` — Primary dedup key (global, unique)
- `default_code` (SKU) — Secondary dedup key (per supplier)
- `api_external_id` — Supplier's external ID

**Three matching rules:**
1. **Barcode ✓ + SKU ✓** → Update existing
2. **Barcode ✓ + SKU ✗** → Update existing (restore SKU)
3. **Barcode ✗ + SKU ✓** → Update existing (add barcode)
4. **Barcode ✗ + SKU ✗** → Create new

### Image Management

- Images auto-downloaded during import
- Converted to RGB JPEG (100 quality)
- Resized to max 1920×1920px
- Stored in product.image_1920
- Nightly cron fills missing images
- URL stored in product.image_url for reference

### Category Hierarchy

- Supplier category tree imported as `supplier.api.category` records
- Automatically maps to `product.public.category` for website
- Parent hierarchy preserved (e.g., Electronics → Resistors → 10kΩ)
- Handles renames and new subcategories
- Detects removed categories (products unpublished, not deleted)

### Product Movement

If supplier moves a product to a different category:
- Product's `supplier_api_category_id` updated
- `public_categ_ids` synced to new category
- Old category links removed
- Notification logged for review

### Counter Refresh

Smart count management:
- Direct count: products linked to THIS category
- Recursive count: products in THIS + all subcategories
- Sync-enabled flag: True if this or any descendant has products
- Parent categories auto-enabled when children are populated

---

## Support

Need help? Have questions? Want a custom connector?

📧 **Email:** support@softg.dev  
🌐 **Website:** https://softg.dev  
📱 **Phone:** +357 96 699 649  

---

## Custom API Development

The module ships with TME Electronics pre-configured. For other suppliers:

- **Mouser Electronics** — Available on request
- **Digi-Key** — Available on request
- **RS Components** — Available on request
- **Farnell / Element14** — Available on request
- **Würth Elektronik** — Available on request
- **Conrad Electronic** — Available on request
- **Your private API** — Custom development available

Contact support@softg.dev to discuss your supplier integration.

---

## Troubleshooting

### Products Not Syncing?

1. Check cron job status: **Settings > Technical > Automation > Scheduled Actions**
2. Look for "Supplier API" crons and verify they're active
3. Check logs: **Settings > Technical > Logs**
4. Manual sync: Open product → Click **Sync from API** button

### Missing Images?

- The module downloads images during import
- Nightly cron (2 AM) fills in missing images
- Or manually click **Sync from API** on a product form

### Category Hierarchy Broken?

- Click **Refresh In Odoo Counts** button on the supplier form
- This rebuilds the category tree and assigns missing products
- Takes a few minutes for large catalogs (1000+ products)

### Stock Not Updating?

1. Verify API credentials are correct
2. Test connection: Click **Test Connection** button
3. Check hourly cron ran: **Settings > Technical > Automation > Scheduled Actions**
4. Manual update: Go to product → Click **Sync from API** button

### Products Not Showing on Website?

1. Check product `is_published` flag (should be True if stock > 0)
2. Check product `sale_ok` flag (should be True)
3. Check website category assigned (Sales tab > Website Categories)
4. Verify product status in website page settings (may be hidden per-page)

### API Connection Fails?

1. Verify token and app secret are correct
2. Check internet connection
3. Verify country/language codes are valid (GB, EN, etc.)
4. Contact TME support if API is down

### Import Hangs or Times Out?

- Large categories (1000+ products) may take time
- Check browser console for errors
- Manual import in batches of 100 products
- Contact support if issues persist

---

## Performance Tips

### Large Catalogs (1000+ products)

1. Import categories in batches of 50-100
2. Use CSV viewer to monitor imports (don't leave it running constantly)
3. Schedule full sync during off-hours (already 2 AM by default)
4. Monitor server logs for timeout errors

### Stock Updates

- Hourly cron updates in batches of 50 products
- If you have 5000 products, cron may take 15-20 minutes
- Adjust cron interval if needed (Settings > Technical > Automation)

### Image Downloads

- Images are auto-downloaded and optimized
- Nightly cron may take extra time on first run
- Consider disabling image auto-download for very large catalogs

---

## FAQ

**Q: Can I use this with suppliers other than TME?**  
A: Yes! The architecture supports any API. Contact us for custom connectors (Mouser, Digi-Key, RS, etc.).

**Q: Will crons delete products if the supplier removes them?**  
A: No. Crons auto-unpublish removed products (hide them) and send you a notification. You can delete them manually or keep them as archived.

**Q: Can I have multiple suppliers?**  
A: Yes. Create separate "Supplier API" records for each API. Each has its own cron jobs and product set.

**Q: What happens if my API credentials are wrong?**  
A: Crons will fail silently (logged). Test connection to verify before running imports.

**Q: Can I modify imported products manually?**  
A: Yes. Manual edits are preserved. Crons update only API-linked fields (price, stock, name, images, categories). Custom fields you add won't be touched.

**Q: How do I stop syncing a specific category?**  
A: Toggle "Sync Enabled" to off on the category form. Products still update via hourly cron, but no new imports happen.

**Q: Can I bulk-delete imported products?**  
A: Yes. Filter by supplier (Inventory > Products > From API TME filter), select all, and delete. Crons won't re-import unless you manually import again.

---

## License

**Odoo Proprietary License (OPL-1)**

This module is proprietary software. Unauthorized copying, modification, or distribution is prohibited.

---

## About Soft G Co. Ltd

Soft G Co. Ltd is a Cyprus-based Odoo specialist team with expertise in:
- E-commerce automation
- Inventory synchronization
- Multi-supplier integrations
- Custom API development
- Odoo implementation & consulting

**Let us handle your supplier integrations. You focus on selling.**

---

## Changelog

### v2.3.2 (Current)
- Multi-category support for products
- Public category hierarchy auto-repair
- Enhanced deduplication logic (EAN → SKU → API ID)
- Improved image download and validation
- Category counter refresh optimization
- Theme Prime compatibility layer
- Post-install hook for data cleanup

### v2.3.1
- Initial Odoo Store release
- TME Electronics connector
- Basic auto-sync crons
- CSV export and viewer

---

Made with ❤️ by **Soft G Co. Ltd**  
v2.3.2 • Odoo 16.0+ • OPL-1  