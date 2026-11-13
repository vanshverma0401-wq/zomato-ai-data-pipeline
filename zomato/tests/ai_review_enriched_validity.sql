{{ config(tags=['ai']) }}

select review_id
from {{ source('ai', 'review_enriched') }}
where sentiment_score is null
   or sentiment_score not between -1 and 1
   or sentiment_label not in ('positive', 'negative', 'neutral')
   or topic not in ('food quality', 'delivery', 'pricing', 'service', 'packaging', 'other')
   or (
       key_issue is not null
       and (
           trim(key_issue) = ''
           or length(key_issue) > 160
           or regexp_count(trim(key_issue), '[^[:space:]]+') > 6
       )
   )
