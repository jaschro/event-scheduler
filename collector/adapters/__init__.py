from . import eventbrite, ics, jsonld, tribe

# method name in sources.yaml -> adapter module
ADAPTERS = {
    "ics": ics,
    "eventbrite": eventbrite,
    "tribe": tribe,
    "jsonld": jsonld,
}
