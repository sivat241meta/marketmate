# Customer flow: price quote

1. Customer opens a shop page (`/s/{slug}`) from the QR on the board, a shared link, or `/market`.
2. Taps "Get a price quote" (`/s/{slug}/quote`) and gives the list in one of three ways: speak it (mic, Muse Voice), type it, or take a photo (of the items picked, or of a handwritten shopping list — Muse Spark reads both).
3. MarketMate identifies each product, takes counts from the photo for countable items and quantities from speech/text, and matches each line to the seller's published prices.
4. The quote page (`/q/{token}`) shows each line (name, qty with - / + stepper, unit price from the seller, line total), unknown items with no price, and the total; "Prices from {shop}'s list, set {relative time}".
5. Customer sends it to the seller on WhatsApp (wa.me link with the quote text and the quote link) or downloads a PDF (`/q/{token}/pdf`). The seller sees it under Bills as a quote waiting.
