from . import eventbrite, ics

# method name in sources.yaml -> adapter module
ADAPTERS = {
    "ics": ics,
    "eventbrite": eventbrite,
}
