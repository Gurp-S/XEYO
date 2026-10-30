"""At-rest effect descriptions shared by selection frontends. No retention decisions here."""
FULL_SOURCE_EFFECT = (
    "Complete source records retained in the prepared view, including payload and public text. "
    "A span or provenance link does not require its source in source_ids."
)
SPAN_EFFECT = (
    "Selected exact public-text spans and source bindings retained in the prepared view. "
    "Their parent records remain independently selectable through source_ids; "
    "span selection alone does not inline a complete parent record."
)
