# Less and Romance — Wholesale Order Form

Generator + latest export of the SS26 wholesale order form. Pulled from the NL Shopify store (`bt0wj0-5j.myshopify.com`, EUR).

## Files

- **`LessAndRomance_Wholesale_OrderForm.xlsx`** — buyer-facing order form (open in Excel/Numbers).
- **`build_orderform.py`** — generator. Reads `shopify_products_snapshot.json`, writes the xlsx.
- **`shopify_products_snapshot.json`** — raw Shopify Admin API export used as the source of truth for this snapshot.
- **`products_query.graphql`** — GraphQL query used to pull the snapshot.

## Workbook structure

| Tab | Purpose |
|---|---|
| Order Info | Buyer details, pricing tier (MOQ logic), live order totals |
| Order Form | 116 variants with retail / wholesale / stock / qty / line total |
| Style Summary | 45 style-color groups, available sizes, stock |
| Terms | MOQ, pricing, payment, delivery, returns |

## MOQ pricing logic

- **MOQ:** €10,000 wholesale subtotal
- **Order ≥ MOQ:** 50% off retail (full wholesale)
- **Order < MOQ:** 22.5% off retail (configurable 20–25% on the Order Info tab)

The discount applied flips automatically as the buyer fills in quantities — driven by named range `AppliedDiscount` and an `IF` on the qualifying subtotal.

## Stock filtering

Out-of-stock variants are excluded from the order form, with three intentional exceptions kept as backorders:

| SKU | Item |
|---|---|
| 47420466856036 | Soft Lounge Kimono Grey Melange — STANDART |
| 47420530163812 | Soft Lounge Long Tee Grey Melange — M |
| 47280364847204 | Soft Lounge Pant Butter Yellow — XS-S |

Adjust the `KEEP_OOS_SKUS` set in `build_orderform.py` to change this list.

## Regenerating

1. Refresh the snapshot:
   ```bash
   CI=1 shopify store execute \
     --store bt0wj0-5j.myshopify.com \
     --query-file products_query.graphql \
     --variables '{"cursor": null}' \
     --json \
     --output-file shopify_products_snapshot.json
   ```
2. Rebuild the xlsx:
   ```bash
   python3 build_orderform.py
   ```

Requires `openpyxl` and an authenticated Shopify CLI session (`shopify store auth --store bt0wj0-5j.myshopify.com --scopes read_products`).
