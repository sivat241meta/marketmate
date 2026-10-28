# MarketMate exports (Task 39)

Sales exports for the shop's own books and for a general POS import.
No network is needed; files are built from the shop's own bills.

Date and time are the shop's local day: Asia/Kolkata for INR shops,
UTC otherwise. Bills count when their local date falls in the range.

## Excel (.xlsx)

Route: `GET /e/{token}/exports/sales.xlsx?range=...&from=...&to=...`

Sheets:

- **Bills**: Bill no, Date, Time, Customer, Payment mode, Items count,
  Total, Round off, Status.
- **Lines**: Bill no, Date, Item (English), Item (local), Qty, Unit,
  Rate, Amount.
- **Items**: Item, Qty sold, Amount (aggregated across the range).
- **Summary**: Date, Bills, Sales, Cash, UPI, Card, Unpaid, Spent,
  Margin (one row per day; Margin is blank when no purchase costs
  are known).

Header row is bold and frozen; money cells use number format `0.00`;
Tamil text is kept as text. On the Lines sheet, rate is per one unit
(price ÷ per_amount); amount is the bill's own line total.

## General POS CSV (UTF-8 with BOM)

Route: `GET /e/{token}/exports/pos.csv?range=...&from=...&to=...`

One row per priced bill line. The file starts with a UTF-8 BOM so
Excel opens Tamil correctly.

Columns:

| Column | Meaning |
|---|---|
| date | Shop-local date, YYYY-MM-DD |
| time | Shop-local time, HH:MM (24h) |
| bill_no | Bill id (integer) |
| item_code | Stable slug of the English name, e.g. `onion`, `small-onion` |
| item_name | English name, lower case, e.g. `tomato` |
| item_name_local | Local name, e.g. `தக்காளி` |
| qty | Quantity sold (number) |
| unit | `kg`, `g`, `piece`, `dozen`, `bunch`, `packet`, `l`, `ml` |
| rate | Unit price per one unit (price ÷ per_amount from the shop list; number, 2 decimals in Excel) — rate is per one unit |
| amount | Line total from the bill (number, qty × rate = amount) |
| discount | Always `0` (no discounts in MarketMate) |
| tax | Always `0` (no tax in MarketMate) |
| bill_total | Rounded bill total (number) |
| payment_mode | `cash`, `upi`, `card`, or empty when unpaid |
| customer_phone | Customer phone or empty |

Example (BOM omitted here):

```csv
date,time,bill_no,item_code,item_name,item_name_local,qty,unit,rate,amount,discount,tax,bill_total,payment_mode,customer_phone
2026-10-27,09:30,1,tomato,tomato,தக்காளி,2,kg,40,80,0,0,110,cash,
2026-10-27,09:30,1,onion,onion,வெங்காயம்,1,kg,30,30,0,0,110,cash,
```

## Price list CSV (general style, UTF-8 with BOM)

Route: `GET /e/{token}/exports/pricelist.csv`

Today's published items, one row per item (first priced line).

Columns: `item_code`, `item_name`, `item_name_local`, `unit`,
`per_amount`, `price`, `sold_out` (`TRUE`/`FALSE`).

Example:

```csv
item_code,item_name,item_name_local,unit,per_amount,price,sold_out
tomato,tomato,தக்காளி,kg,1,40,FALSE
onion,onion,வெங்காயம்,kg,1,30,FALSE
```

The existing POS-app price-list CSV is unchanged.
