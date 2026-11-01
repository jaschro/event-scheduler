from . import custom, eventbrite, ics, jsonld, ticketmaster, tribe

# method name in sources.yaml -> adapter module.
# "custom" and "browser" both dispatch to the per-venue module named by `reader`.
ADAPTERS = {
    "ics": ics,
    "eventbrite": eventbrite,
    "tribe": tribe,
    "jsonld": jsonld,
    "custom": custom,
    "browser": custom,
    "ticketmaster": ticketmaster,
}
