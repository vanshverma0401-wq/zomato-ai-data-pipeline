{{ config(tags=['ai']) }}

select city, topic, sentiment_label
from {{ ref('mart_review_insights') }}
group by city, topic, sentiment_label
having count(*) > 1

union all

select city, topic, sentiment_label
from {{ ref('mart_review_insights') }}
where reviews <= 0
   or flagged_issues < 0
   or flagged_issues > reviews
   or avg_sentiment_score not between -1 and 1
