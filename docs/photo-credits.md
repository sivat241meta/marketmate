# Landing page photo credits (Task 81)

The five marketing photos below were approved by the owner for the
MarketMate landing page (`app/web/templates/home.html`, images in
`app/web/static/landing/`). They are photos of people used to tell the
product's story. They are **never** product photos: no shop or product
template may reference them.

Licence for all five: **Unsplash License** (https://unsplash.com/license).
Each photo was downloaded at 1600px wide, re-encoded with Pillow
(progressive JPEG, EXIF stripped; quality 80 unless noted, kept under
350 KB), plus an 800px-wide variant for `srcset`.

| File | Unsplash ID | Photographer | Page | SHA-256 (1600px file) |
|---|---|---|---|---|
| hero.jpg | czt2KF17CtE | Frédéric Barriol | https://unsplash.com/photos/czt2KF17CtE | 257e395eb1327c4269f2d91c3f78553ed466980c374a0471e662805add6c4368 |
| seller-phone.jpg | CBucCjSOuuY | Ashwini Chaudhary (Monty) | https://unsplash.com/photos/CBucCjSOuuY | a9a2bce5628a084b6f95656314b4ea10550f818b3a71d3ba41f0ca1bf993c5ef |
| banana-cart.jpg | GuBFtfzosaY | Aditya Sethia | https://unsplash.com/photos/GuBFtfzosaY | d7f668d19e0c406bb4cdc8e3a9d33017fd0c359cc58b57a9a167ac8d1a5925a1 |
| street-market.jpg | P0lXf8uN75Y | Abdullah Azeez | https://unsplash.com/photos/P0lXf8uN75Y | 341a2e69a67a806e29bcf1cf431dd3e265db55a836ecd8d48b8a213af859945f |
| customer-phone.jpg | iJfM5uaZ1N4 | Emil Widlund | https://unsplash.com/photos/iJfM5uaZ1N4 | 7c25e56a37cc63fec5258e23bdf39c67dcf1a6bf3b2bd4d566c459ee1abeb3dc |

800px variants (`*-800.jpg`) and their hashes:

- hero-800.jpg — 3687bd31de7c47598d25ce146644a3ca7346b203f0be5d0479b129538093e4ba
- seller-phone-800.jpg — 3ab6e81e35665749ceb866aff20fadeb6e151d915f415c720a4547ff276f941d
- banana-cart-800.jpg — 65a4ec31abcd3e787d44889ac1cf6c122b1d4097200f290da8a75741d5176ef3
- street-market-800.jpg — 099fed09b644b529b8737e861974748b1075d00b6fb3ae0ef84c01fcb6a4e9d1
- customer-phone-800.jpg — ddbf3a22c0bd185b66775aaae2c3b703fe45ce0aa9c00717eb5a7d2281cbb89c

Encode notes: hero.jpg and street-market.jpg are quality 65,
customer-phone.jpg is quality 75, the rest are quality 80 — each kept
at the highest quality that stays under 350 KB at 1600px.
Every file's caption on the page reads "Photo: <name> / Unsplash".
