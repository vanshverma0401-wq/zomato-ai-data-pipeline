# Data acquisition and provenance

The dataset is intentionally excluded from Git. Download the creator-provided files from the [dataset and slides folder linked by the tutorial](https://drive.google.com/drive/folders/1FEnGWMHhHzzTUCZOw1-YnH2v3DMuM-rs?usp=sharing). The source of that acquisition route is the [creator's README pinned at commit 57d147dfe6aaed6bfe7c215d74185c39358790a4](https://github.com/darshilparmar/zomato-ai-data-engineering-end-to-end-project/blob/57d147dfe6aaed6bfe7c215d74185c39358790a4/README.md).

The creator describes four dimension CSVs (`restaurant`, `users`, `food`, `menu`) and three generated fact CSVs (`orders`, `order_items`, `reviews`). The review texts in this exercise are part of the generated tutorial data. They are useful for demonstrating pipelines and AI behavior; they are not evidence of observed customer sentiment, real operating revenue, or measured customer demand.

Reproduction here uses the creator's pre-generated fact CSVs. No generation script was verified in the pinned source, and this export does not invent one or claim to recreate the original generation process. If the external download becomes unavailable or its release changes, the exact training exercise cannot be reproduced from this repository alone. Record the download date, CSV headers, sizes and checksums privately for your acquired release. Review its terms before redistributing any data.

## File layout and schema

Upload files into a private bucket using these prefixes. The stage URL ends in `/raw/`, so the loader's `restaurants/` path is relative to that URL.

| S3 key pattern | Snowflake RAW table | Relevant input shape |
|---|---|---|
| `raw/restaurants/restaurant.csv` | `RESTAURANTS` | Leading unnamed index, then restaurant ID/name/city/rating/cost/cuisine and other dimension attributes |
| `raw/users/users.csv` | `USERS` | Leading unnamed index, then user ID/name/email and other dimension attributes |
| `raw/food/food.csv` | `FOOD` | Leading unnamed index, then food ID/item/vegetarian indicator |
| `raw/menu/menu.csv` | `MENU` | Leading unnamed index, then menu ID/restaurant ID/food ID/cuisine/price |
| `raw/orders/orders.csv` | `ORDERS` | Generated transaction records; no leading index |
| `raw/order_items/order_items.csv` | `ORDER_ITEMS` | Generated order-line records; no leading index |
| `raw/reviews/reviews.csv` | `REVIEWS` | Generated review records and comment text; no leading index |

Exact positional column order and types are in [snowflake/04_raw_tables.sql](../snowflake/04_raw_tables.sql), preserved from the [pinned upstream DDL](https://github.com/darshilparmar/zomato-ai-data-engineering-end-to-end-project/blob/57d147dfe6aaed6bfe7c215d74185c39358790a4/snowflake/04_raw_tables.sql):

```text
orders:
order_id, order_timestamp, order_date, user_id, r_id, restaurant_city,
cuisine, items_count, sales_qty, subtotal, discount, delivery_fee, gst,
sales_amount, currency, payment_method, order_status, customer_rating,
delivery_time_min

order_items:
order_item_id, order_id, r_id, f_id, price, quantity, line_amount

reviews:
review_id, order_id, user_id, restaurant_id, rating, comment, review_date
```

The CSV format skips one header row and reads columns by position. `restaurant.csv` is singular even though its table and folder are plural. Verify your acquired files against the DDL before loading. Row counts quoted in the creator's tutorial describe that source release; your own COPY outcomes and counts must be measured after loading. No raw rows, personal fields from the dataset, or claimed live results are included in this document.
