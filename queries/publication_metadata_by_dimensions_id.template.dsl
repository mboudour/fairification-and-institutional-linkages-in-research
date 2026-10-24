# Template only — replace the placeholder locally; do not commit IDs or responses.
# Purpose: retrieve publication identity and text fields for an already accepted
# local Dimensions publication anchor. No relational outcome fields are requested.

search publications where id in ["YOUR_DIMENSIONS_PUBLICATION_ID"]
return publications[id+doi+title+abstract+year+date+document_type+type+journal_title_raw] limit 25
