"""R20 is not a second inbox.

The board card is a link to the official Sesizări app (that link is frontend) plus a count.
The count is `GET /api/closures/{id}/reports?since=` on the existing sesizări recording
(`since` is the closure's publishedAt). This module does not register a router: a POST that
stores traveller signals would be a parallel reporting channel. The models in this package
describe a draft that stores a category code, never free text; nothing here is mounted.
"""
