"""Seller + customer labels in English, Tamil and Hindi.

One dict per language, keys grouped by page. ``t_for(lang)`` returns a
``t(key, **vars)`` helper with English fallback. Templates use the Jinja
global ``t`` (request UI language); customer pages keep passing ``t`` dicts
via ``get_strings`` for their ``?lang`` behaviour.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# English catalogue (source of truth for keys)
# ---------------------------------------------------------------------------

_ENGLISH: dict[str, str] = {
    # --- customer shop / quote (Task 29, kept) ---
    "prices_set_by_seller": "Prices set by the seller",
    "spoken_and_checked": "spoken and checked",
    "get_quote": "Get a price quote",
    "call": "Call",
    "whatsapp": "WhatsApp",
    "sold_out": "Sold out",
    "no_prices": "No prices published yet.",
    "quote_subtitle": "Prices from this shop's list, set {rel}",
    "check_quantity": "check quantity",
    "per": "per",
    "update_quote": "Update quote",
    "total": "Total",
    "your_total": "Your total",
    "no_prices_title": "This shop hasn't shared today's prices yet",
    "priced": "priced",
    "not_priced": "not priced",
    "not_on_list": "not on this shop's list",
    "send_whatsapp": "Send on WhatsApp",
    "pdf": "PDF",
    "back_to": "Back to",
    "no_items": "No items on this quote yet.",
    "speak_list": "Speak your list",
    "speak_help": "Say what you need, e.g. “2 kilo tomato, 1 dozen banana”.",
    "speak": "Speak",
    "stop": "Stop",
    "tap_speak": "Tap Speak and say your list.",
    "upload_recording": "Or upload a recording",
    "upload_and_quote": "Upload and quote",
    "type_list": "Type your list",
    "what_need": "What do you need?",
    "get_quote_short": "Get quote",
    "photo_list": "Photo your list",
    "photo_help": "A photo of the items you picked, or of a handwritten shopping list.",
    "choose_photo": "Choose a photo",
    "upload_photo_quote": "Upload photo and quote",
    # --- topbar / footer (base) ---
    "top.find_prices": "Find prices",
    "top.start_selling": "Start selling",
    "top.footer": "MarketMate · Every price comes from the seller's own voice. Nothing is guessed.",
    "top.main_nav": "Main",
    "top.lang_label": "Language",
    # --- sidebar ---
    "nav.dashboard": "Dashboard",
    "nav.prices": "Prices",
    "nav.live_prices": "Live prices",
    "nav.photos": "Photos",
    "nav.bills": "Bills",
    "nav.purchases": "Purchases",
    "nav.close": "Close day",
    "nav.shop_page": "Shop page",
    "nav.settings": "Settings",
    "nav.seller_label": "Seller",
    # --- dashboard ---
    "dash.title_suffix": "dashboard",
    "dash.test_shop": "Test shop - not listed in the market, deleted after 7 days",
    "dash.live_pill": "Live · {count} prices",
    "dash.shop_link": "Your shop link · {url}",
    "dash.copy": "Copy",
    "dash.copied": "Copied",
    "dash.share": "Share",
    "dash.qr": "QR",
    "dash.copy_prompt": "Copy your shop link:",
    "dash.share_title": "MarketMate shop",
    "dash.live_prices": "Live prices",
    "dash.live_desc": "Point at your stall and say each price. Cards appear as you speak.",
    "dash.go_live": "Go live",
    "dash.upload_label": "Or upload a video of your stall",
    "dash.upload_help": "Up to 3 minutes. Film each item as you say its price.",
    "dash.cancel_upload": "Cancel upload",
    "dash.upload_video": "Upload a video",
    "dash.upload_progress": "Upload progress",
    "dash.tile_update": "Update by voice",
    "dash.tile_scan": "Scan stock photo",
    "dash.tile_bills": "Bills",
    "dash.tile_bills_sub": "{sales} today · {waiting} waiting",
    "dash.tile_purchases": "Purchases",
    "dash.tile_purchases_sub": "Spent today {spent}",
    "dash.tile_print_board": "Print board",
    "dash.tile_print_tags": "Print price tags",
    "dash.tile_export_csv": "Export CSV",
    "dash.tile_posapp_csv": "POS-app CSV",
    "dash.stock_total": "{total} in stock (version {vid})",
    "dash.stock_left_out": "Not counted: {items}",
    "dash.todays_list": "Today's list",
    "dash.edit": "Edit",
    "dash.sold_out": "Sold out",
    "dash.back_in_stock": "Back in stock",
    "dash.per": "per {per}",
    "dash.stock_line": "Stock: about {qty} ({source})",
    "dash.no_prices_title": "No prices yet",
    "dash.no_prices_text": "Record today's prices to build your first list.",
    "dash.recent_sessions": "Recent sessions",
    "dash.session": "Session {id}",
    "dash.no_uploads": "No uploads yet.",
    "dash.versions": "Versions",
    "dash.version": "Version {id}",
    "dash.published": "Published",
    "dash.unpublish": "Unpublish",
    "dash.publish": "Publish",
    "dash.no_versions": "No approved price lists yet.",
    # --- session / processing ---
    "sess.title": "Session {id}",
    "sess.failed_title": "Something went wrong",
    "sess.try_again": "Try again",
    "sess.back_dashboard": "Back to dashboard",
    "sess.approved_text": "Approved ✓ — the price list is saved.",
    "sess.back_shop": "Back to shop",
    "sess.voice_waiting": "These changes are waiting on the confirm page. If you closed it, record the update again.",
    "sess.update_by_voice": "Update prices by voice",
    "sess.working_photo": "Working on your photo…",
    "sess.working_board": "Reading your price board…",
    "sess.working_purchases": "Working on your purchases…",
    "sess.working_video": "Working on your video…",
    "sess.step_of": "Step {step} of {total}",
    "sess.elapsed_s": "Elapsed: {s} s",
    "sess.elapsed_m": "Elapsed: {m} min {s} s",
    "sess.refresh_note": "Working on it… this page refreshes every 3 s.",
    "sess.making_bill": "Making the bill…",
    "sess.making_bill_title": "Making the bill — {shop}",
    "sess.back_bills": "Back to bills",
    # --- stages (labels) ---
    "stage.video.uploaded": "Video received",
    "stage.video.audio": "Getting the sound out",
    "stage.video.listening": "Listening to your prices",
    "stage.video.items": "Finding the items",
    "stage.video.photos": "Picking a photo for each item",
    "stage.video.checking": "Checking every price",
    "stage.video.ready": "Ready to check",
    "stage.photo.uploaded": "Photo received",
    "stage.photo.looking": "Looking at your photo",
    "stage.photo.counting": "Counting each item",
    "stage.photo.suggesting": "Preparing suggestions",
    "stage.photo.ready": "Ready to check",
    "stage.quote.received": "Request received",
    "stage.quote.listening": "Listening",
    "stage.quote.looking": "Looking",
    "stage.quote.matching": "Matching prices",
    "stage.quote.ready": "Quote ready",
    "stage.live.listening": "Listening live",
    "stage.live.items": "Finding the items",
    "stage.live.checking": "Checking every price",
    "stage.live.ready": "Ready to check",
    "stage.board.uploaded": "Photo received",
    "stage.board.looking": "Reading your board",
    "stage.board.items": "Finding the items",
    "stage.board.checking": "Checking every price",
    "stage.board.ready": "Ready to check",
    "stage.purchase.uploaded": "Recording received",
    "stage.purchase.listening": "Listening to your purchases",
    "stage.purchase.items": "Finding the items",
    "stage.purchase.checking": "Checking every number",
    "stage.purchase.ready": "Ready to check",
    # --- stages (friendly lines) ---
    "friendly.video.uploaded": "Your recording arrived safely.",
    "friendly.video.audio": "Getting the sound out of your video.",
    "friendly.video.listening": "Meta Muse Voice is turning your speech into text.",
    "friendly.video.items": "Muse Spark is finding the items and prices you said.",
    "friendly.video.photos": "Picking a photo for each item.",
    "friendly.video.checking": "Checking every price against what you said.",
    "friendly.video.ready": "Ready for you to check.",
    "friendly.photo.uploaded": "Your photo arrived safely.",
    "friendly.photo.looking": "Muse Spark is looking at your photo.",
    "friendly.photo.counting": "Counting each item in the photo.",
    "friendly.photo.suggesting": "Preparing suggestions for you.",
    "friendly.photo.ready": "Ready for you to check.",
    "friendly.quote.received": "Your request arrived safely.",
    "friendly.quote.listening": "Muse Voice is turning your speech into text.",
    "friendly.quote.looking": "Muse Spark is reading your photo.",
    "friendly.quote.matching": "Matching each line to the shop's prices.",
    "friendly.quote.ready": "Your quote is ready.",
    "friendly.live.listening": "Listening live to your prices.",
    "friendly.live.items": "Muse Spark is finding the items and prices you said.",
    "friendly.live.checking": "Checking every price against what you said.",
    "friendly.live.ready": "Ready for you to check.",
    "friendly.board.uploaded": "Your board photo arrived safely.",
    "friendly.board.looking": "Muse Spark is reading your price board.",
    "friendly.board.items": "Finding the items and prices on your board.",
    "friendly.board.checking": "Checking every price from your board.",
    "friendly.board.ready": "Ready for you to check.",
    "friendly.purchase.uploaded": "Your recording arrived safely.",
    "friendly.purchase.listening": "Meta Muse Voice is turning your speech into text.",
    "friendly.purchase.items": "Muse Spark is finding what you bought.",
    "friendly.purchase.checking": "Checking every number against what you said.",
    "friendly.purchase.ready": "Ready for you to check.",
    # --- review ---
    "review.title": "Check prices",
    "review.counts": "{ok} of {total} look right · {need} need you",
    "review.counts_aria": "{ok} of {total} prices look right",
    "review.check_again": "Check again",
    "review.check_again_title": "Run the checks again from your recording",
    "review.needs_you": "Needs you",
    "review.looks_right": "Looks right",
    "review.read_from_board": "Read from your board",
    "review.play": "Play what you said",
    "review.price": "Price",
    "review.per": "Per",
    "review.unit": "Unit",
    "review.remove": "✕ Remove",
    "review.remove_aria": "Remove this price line",
    "review.quantity": "Quantity",
    "review.edit_note": "You changed this from what was heard. Play the clip, then tick I confirm.",
    "review.confirm": "I confirm",
    "review.approve": "Approve price list",
    "review.no_price": "no price yet",
    # --- flags ---
    "flag.sound_alike": "did you say {a} or {b}?",
    "flag.sound_alike_ta": "did you say {a} or {b}? ({x} and {y} sound alike in Tamil)",
    "flag.sound_alike_hi": "did you say {a} or {b}? ({x} and {y} sound alike in Hindi)",
    "flag.sound_alike_mr": "did you say {a} or {b}? ({x} and {y} sound alike in Marathi)",
    "flag.sound_alike_bn": "did you say {a} or {b}? ({x} and {y} sound alike in Bengali)",
    "flag.sound_alike_half": "did you say half a {unit} or 6 {unit}? (arai and aaru sound alike in Tamil)",
    "flag.sound_alike_zh": "did you say dozen or bunch? ({x} and {y} sound alike in Mandarin)",
    "flag.sound_alike_th": "did you say dozen or kg? ({x} and {y} sound alike in Thai)",
    "flag.matches_previous": "{price} matches the previous price ({rate} per {unit})",
    "flag.not_heard_price": "price {price} not heard in quote",
    "flag.not_heard_qty": "quantity {qty} not heard in quote",
    "flag.not_heard_total": "total {total} not heard in quote",
    "flag.number_check": "we are not sure about this number - please listen",
    "flag.unit_missing": "price is missing its unit",
    "flag.unit_missing_qty": "quantity is missing its unit",
    "flag.unit_odd": "usually sold by weight - is per piece right?",
    "flag.unit_check": "please check the unit",
    "flag.unit_from_earlier": "unit was taken from the current price",
    "flag.jump": "price jumped from {old} to {current} per {unit} (last confirmed)",
    "flag.range": "seller said a range, pick one number",
    "flag.two_prices": "two prices for the same amount",
    "flag.no_price": "no price at all",
    "flag.no_total": "no total paid heard",
    "flag.qty_missing": "no quantity",
    "flag.qty_missing_heard": "no quantity heard",
    "flag.correction": "seller corrected themselves (\"{marker}\")",
    "flag.unclear_number": "unclear number \"{before}\" before currency",
    "flag.board_confirm": "read from your board – tap to confirm",
    "flag.not_read": "{name} could not be read from your board – type the price",
    "flag.new_item": "{name} is not in the current price list",
    # --- voice update ---
    "upd.confirm_title": "Confirm price changes",
    "upd.record_title": "Update prices by voice",
    "upd.heard": "Heard: {transcript}",
    "upd.sold_out_was": "Sold out — was {summary}",
    "upd.back_in_stock": "Back in stock — {summary}",
    "upd.no_changes": "No changes heard. Nothing to confirm.",
    "upd.confirm_publish": "Confirm and publish",
    "upd.say_changes": "Say today's changes, e.g. “thakkali 22, vengayam sold out”. No video needed.",
    "upd.say_price_for": "Say the price for {hint} — e.g. “{hint} 20 rupees a kilo”.",
    "upd.start_rec": "Start recording",
    "upd.stop_check": "Stop and check",
    "upd.tap_start": "Tap Start and say the new prices.",
    "upd.upload_rec": "Or upload a recording",
    "upd.upload_check": "Upload and check",
    "upd.board_title": "Photo of your price board",
    "upd.board_desc": "Take a photo of your handwritten or printed board. We read each price — you tap every price to confirm before anything is published.",
    "upd.board_choose": "Choose a photo of your board",
    "upd.board_upload": "Upload board and check",
    "upd.current_prices": "Current prices",
    "upd.sold_out_label": "sold out",
    "upd.price_line": "{price} per {amount} {unit}",
    "upd.no_list": "No approved price list yet — upload a video first.",
    "upd.action_set_price": "New price",
    "upd.action_sold_out": "Sold out",
    "upd.action_in_stock": "Back in stock",
    "upd.action_set_qty": "New quantity",
    # --- live ---
    "live.title": "Live prices — {shop}",
    "live.live": "Live",
    "live.camera_preview": "Camera preview",
    "live.start_aria": "Start live prices",
    "live.tap_start": "Tap to start. Point at your stall and say each price.",
    "live.finishing": "Finishing… checking every price",
    "live.ready": "Ready",
    "live.finishing_live": "Finishing – checking every price…",
    "live.upload_instead": "Upload a video instead",
    "live.heard": "Prices heard",
    "live.no_prices": "No prices yet — start talking.",
    "live.no_support": "Live mode needs a browser with camera and microphone support. You can still upload a video.",
    "live.video_label": "Video of your stall",
    "live.video_help": "Up to 3 minutes. Film each item as you say its price.",
    "live.back": "Back to dashboard",
    # --- photos list ---
    "pho.title": "Stock photos — {shop}",
    "pho.heading": "Stock photos",
    "pho.sub": "{shop} · counts are estimates, prices come from your voice",
    "pho.scan_title": "Scan a stock photo",
    "pho.scan_desc": "Take a photo of a crate or heap. We count what is visible. Prices only come from what you say.",
    "pho.drop_camera": "Point the camera at one crate or heap, in good light.",
    "pho.choose": "Choose photo",
    "pho.scan_btn": "Scan this photo",
    "pho.gallery_label": "Or choose from gallery",
    "pho.gallery_btn": "Upload from gallery",
    "pho.past": "Past checks",
    "pho.empty_title": "No photo checks yet",
    "pho.empty_text": "Scan your first stock photo above.",
    # --- photo result ---
    "phr.title": "Photo check — {shop}",
    "phr.back": "← All photo checks",
    "phr.heading": "Photo check",
    "phr.sub": "{shop} · {rel}",
    "phr.scanned_alt": "Scanned stock photo",
    "phr.counted_aria": "Counted items",
    "phr.show_boxes": "Show boxes",
    "phr.what_we_see": "What we see",
    "phr.sold_by_weight": "Sold by weight - no count",
    "phr.count_less": "Count one less",
    "phr.count_more": "Count one more",
    "phr.count_for": "Count for {display}",
    "phr.suggestions": "Suggestions",
    "phr.no_suggestions": "Nothing to suggest for this photo.",
    "phr.notes": "Notes for you",
    "phr.seller_only": "Seller only: {name} — {note}",
    "phr.honesty": "Counts are estimates from the photo. Prices only come from what you say.",
    "phr.count_about": "About {n} visible",
    "phr.count_range": "Between {a} and {b} - please check",
    "phr.count_about_check": "About {n} - some may be hidden, please check",
    "phr.sugg_retake": "Photo looks {quality}. Take it again closer, in good light.",
    "phr.sugg_add_price": "{name} is not on your price list. Say its price to add it.",
    "phr.sugg_back": "{name} is in the photo but marked sold out. Put it back on sale?",
    "phr.sugg_check_count": "{name}: we counted between {low} and {high}. Please check.",
    "phr.sugg_set_stock": "About {count} {name} visible. Save as today's stock?",
    "phr.btn_save_stock": "Save stock",
    "phr.btn_back_sale": "Put back on sale",
    "phr.btn_say_price": "Say its price",
    "phr.btn_retake": "Retake photo",
    "phr.quality_dark": "dark",
    "phr.quality_blurry": "blurry",
    "phr.quality_far": "too far",
    # --- bills dashboard ---
    "bills.title": "Bills — {shop}",
    "bills.heading": "Bills",
    "bills.sub": "{shop} · today's sales at a glance",
    "bills.today": "Today",
    "bills.yesterday": "Yesterday",
    "bills.week": "Last 7 days",
    "bills.bills_today": "Bills today",
    "bills.billed_paid": "billed and paid",
    "bills.sales_today": "Sales today",
    "bills.total_billed": "total billed",
    "bills.quotes_waiting": "Quotes waiting",
    "bills.from_customers": "from customers",
    "bills.avg_bill": "Average bill",
    "bills.per_bill": "per bill today",
    "bills.cash": "Cash",
    "bills.paid_today": "paid today",
    "bills.upi": "UPI",
    "bills.card": "Card",
    "bills.new_bill": "New bill",
    "bills.filter_all": "All",
    "bills.filter_waiting": "Quotes waiting",
    "bills.filter_billed": "Billed",
    "bills.filter_paid": "Paid",
    "bills.item_one": "{count} item",
    "bills.item_many": "{count} items",
    "bills.walk_in": "Walk-in",
    "bills.time_yesterday": "Yesterday {clock}",
    "bills.pill_quote": "Quote",
    "bills.pill_billed": "Billed",
    "bills.pill_paid": "Paid",
    "bills.pill_cancelled": "Cancelled",
    "bills.empty_title": "No bills here yet",
    "bills.empty_text": "Bills you make today will show up here. Tap New bill to start one.",
    "bills.top_today": "Top items today",
    "bills.sold": "{qty} {unit} sold",
    "bills.share_sales": "{display} share of sales",
    "bills.nothing_title": "Nothing billed yet",
    "bills.nothing_text": "Your best sellers will show up here once you bill today.",
    "bills.exports": "Exports",
    "bills.date_range": "Date range",
    "bills.month": "This month",
    "bills.custom": "Custom",
    "bills.from": "From",
    "bills.to": "To",
    "bills.excel": "Excel (.xlsx)",
    "bills.pos_csv": "General POS CSV",
    "bills.pricelist_csv": "Price list CSV",
    "bills.date_aria": "Date range",
    "bills.filter_aria": "Filter bills",
    # --- bill page ---
    "bill.title": "Bill {id} — {shop}",
    "bill.back": "← All bills",
    "bill.heading": "Bill #{id}",
    "bill.receipt_aria": "Bill receipt",
    "bill.check_qty": "check quantity",
    "bill.round_off": "Round off {off}",
    "bill.exact": "{exact} exact",
    "bill.update": "Update bill",
    "bill.remove": "Remove {display}",
    "bill.no_items": "No items on this bill yet. Add one below.",
    "bill.accept_quote": "Accept quote",
    "bill.collect": "Collect payment",
    "bill.scan_upi": "Scan with any UPI app",
    "bill.add_upi": "Add your UPI ID in Settings to collect UPI payments with a QR.",
    "bill.paid_cash": "Paid by cash",
    "bill.paid_upi": "Paid by UPI",
    "bill.paid_card": "Paid by card",
    "bill.cash_helper": "Cash helper",
    "bill.customer_gave": "Customer gave",
    "bill.exact_chip": "exact",
    "bill.give_back": "Give back {amount}",
    "bill.paid_state": "Paid",
    "bill.paid_by": "Paid by {mode}",
    "bill.scan_title": "Customer can scan to get the bill",
    "bill.share_wa": "Share on WhatsApp",
    "bill.print_pdf": "Print / PDF",
    "bill.cust_phone": "Customer phone",
    "bill.wa_number": "WhatsApp number for the receipt",
    "bill.walkin_help": "Leave blank for a walk-in customer.",
    "bill.save_phone": "Save phone",
    "bill.add_item": "Add an item",
    "bill.from_list": "Item from today's list",
    "bill.add_btn": "Add item",
    "bill.no_pricelist": "No price list yet.",
    "bill.not_on_list": "not on this shop's list",
    "bill.less_aria": "One less {display}",
    "bill.more_aria": "One more {display}",
    "bill.qty_aria": "Quantity for {display}",
    "bill.weight_chip": "⌨ weight",
    "bill.weight_aria": "Type exact weight for {display}",
    "bill.amount_chip": "₹ amount",
    "bill.amount_aria": "Enter rupee amount for {display}",
    "bill.cancel": "Cancel",
    "bill.ok": "OK",
    "bill.sold_out": "Sold out",
    "bill.no_price_yet": "No price yet",
    # --- new bill ---
    "bn.title": "New bill — {shop}",
    "bn.back": "← All bills",
    "bn.heading": "New bill",
    "bn.sub": "{shop} · prices from today's list",
    "bn.method_aria": "Bill method",
    "bn.tap": "Tap items",
    "bn.speak": "Speak",
    "bn.type": "Type",
    "bn.photo": "Photo",
    "bn.tap_desc": "Fastest: tap + for each item. No AI, totals from your list.",
    "bn.pick_items": "Pick items with +",
    "bn.make_bill": "Make bill",
    "bn.no_list": "No price list yet. Record today's prices first.",
    "bn.speak_title": "Speak the order",
    "bn.speak_desc": "Say the order, e.g. “2 kilo tomato, 1 dozen banana”.",
    "bn.live_start_aria": "Start live billing",
    "bn.live_hint": "Tap to start. Lines appear as you speak.",
    "bn.bill_so_far": "Bill so far",
    "bn.total_label": "Total:",
    "bn.done": "Done",
    "bn.upload_instead": "Upload a recording instead",
    "bn.speak_label": "Speak",
    "bn.stop": "Stop",
    "bn.tap_speak_order": "Tap Speak and say the order.",
    "bn.or_upload": "Or upload a recording",
    "bn.choose_rec": "Choose recording",
    "bn.upload_bill": "Upload and bill",
    "bn.type_title": "Type it",
    "bn.what_took": "What did the customer take?",
    "bn.type_placeholder": "2 kg tomato, 1 dozen banana",
    "bn.photo_title": "Photo the basket",
    "bn.photo_desc": "A photo of the customer's basket. We count and price from your list.",
    "bn.photo_choose_label": "Choose a photo of the basket",
    "bn.photo_choose": "Choose photo",
    "bn.photo_btn": "Upload photo and bill",
    # --- settings ---
    "set.title": "Settings — {shop}",
    "set.heading": "Settings",
    "set.sub": "{shop} · your shop, your way",
    "set.profile": "Shop profile",
    "set.name": "Shop name",
    "set.area": "Area",
    "set.phone": "Phone / WhatsApp",
    "set.phone_help": "7–15 digits, optional leading +.",
    "set.language": "Language",
    "set.lang_help": "The language you speak your prices in.",
    "set.currency": "Currency",
    "set.type": "Shop type",
    "set.upi": "UPI ID",
    "set.upi_help": "Optional. Needed for UPI QR payments.",
    "set.payee": "UPI payee name",
    "set.payee_help": "Shown in the customer's UPI app. Defaults to shop name.",
    "set.round": "Round bills to the nearest rupee",
    "set.round_help": "Bill totals round to whole rupees; the round-off shows on the bill.",
    "set.save": "Save settings",
    "set.seller_link": "Your seller link",
    "set.seller_desc": "Open your dashboard, bills and prices from any device.",
    "set.keep_private": "Keep this link private: anyone with this link can change your prices.",
    "set.copy_prompt": "Copy your seller link:",
    # --- task 41: install, offline, order status, helpers, link safety ---
    "dash.install_app": "Install app",
    "dash.install_hint": "Add MarketMate to your home screen for one-tap billing.",
    "dash.install_ios": "On iPhone: Share → Add to Home Screen.",
    "dash.send_link_wa": "Send my link to my WhatsApp",
    "dash.keep_safe": "Keep this safe",
    "bills.filter_packing": "Packing",
    "bills.filter_ready": "Ready",
    "bills.filter_collected": "Collected",
    "bills.pill_packing": "Packing",
    "bills.pill_ready": "Ready",
    "bills.pill_collected": "Collected",
    "bill.start_packing": "Start packing",
    "bill.mark_ready": "Ready for pickup",
    "bill.mark_collected": "Collected",
    "bill.cancel_order": "Cancel order",
    "bill.tell_whatsapp": "Tell the customer on WhatsApp",
    "bill.price_changed": "Price changed while offline — please check each line before collecting.",
    "bill.made_by": "Made by {name}",
    "bill.order_status": "Order status",
    "set.add_helper": "Add a helper",
    "set.helper_name": "Helper name",
    "set.helper_desc": "Helpers can only make bills. They cannot change prices, photos, purchases, settings, exports or day close.",
    "set.helper_once": "Share this link now — it will not be shown again.",
    "set.helper_remove": "Remove",
    "set.no_helpers": "No helpers yet.",
    "set.send_link_wa": "Send my link to my WhatsApp",
    "set.keep_safe": "Keep this safe",
    "set.keep_safe_desc": "Print this card and keep it in your shop. Anyone with this link can run your shop.",
    "set.print_card": "Print safe card",
    "error.helper_title": "Helpers can only make bills",
    "error.helper_message": "This page changes your shop, so helpers cannot open it. Ask the shop owner.",
    "order.step_new": "Order received",
    "order.step_packing": "Packing your order",
    "order.step_ready": "Ready for pickup",
    "order.step_collected": "Collected",
    "order.step_cancelled": "Cancelled",
    "order.status_label": "Order status",
    # --- purchases ---
    "pur.title": "Purchases — {shop}",
    "pur.heading": "Today's purchases",
    "pur.sub": "{shop} · {today} · Spent today {spent}",
    "pur.say_title": "Say what you bought",
    "pur.say_desc": "E.g. “onion 50 kilo 1200 rupees”. Every number must be heard.",
    "pur.upload_label": "Upload a recording",
    "pur.upload_check": "Upload and check",
    "pur.type_title": "Type one row",
    "pur.item": "Item",
    "pur.qty": "Quantity",
    "pur.unit": "Unit",
    "pur.total_paid": "Total paid",
    "pur.add": "Add purchase",
    "pur.bought_today": "Bought today",
    "pur.paid_cost": "paid {total} · cost {cost}",
    "pur.stock_left": "Stock left: {left}",
    "pur.empty_title": "Nothing bought yet",
    "pur.empty_text": "Say or type what you bought at the market this morning.",
    "pur.recent": "Recent voice notes",
    "pur.purchase_n": "Purchase {id}",
    "pur.buy": "buy",
    "pur.sell": "sell",
    # --- purchase review ---
    "pr.title": "Confirm purchases",
    "pr.heading": "Confirm purchases",
    "pr.heard": "Heard: {transcript}",
    "pr.qty_total": "{qty} {unit} · total {total}",
    "pr.nothing": "Nothing heard. Try again.",
    "pr.confirm_btn": "Confirm purchases",
    # --- day close ---
    "close.title": "Close day {day} — {shop}",
    "close.heading": "Close day",
    "close.sub": "{shop} · {day}",
    "close.day": "Day",
    "close.show": "Show",
    "close.sales": "Sales",
    "close.billed_paid": "billed and paid",
    "close.bills": "Bills",
    "close.spent": "Spent on purchases",
    "close.market_run": "market run",
    "close.margin": "Gross margin",
    "close.margin_sub": "sales minus cost",
    "close.cash": "Cash",
    "close.paid": "paid",
    "close.upi": "UPI",
    "close.card": "Card",
    "close.unpaid": "Unpaid",
    "close.billed_not_paid": "billed, not paid",
    "close.items_sold": "Items sold",
    "close.th_item": "Item",
    "close.th_sold": "Sold",
    "close.th_sales": "Sales",
    "close.th_opening": "Opening",
    "close.th_left": "Stock left",
    "close.th_wastage": "Wastage",
    "close.wastage_aria": "Wastage for {display}",
    "close.save_wastage": "Save wastage",
    "close.nothing_title": "Nothing billed",
    "close.nothing_text": "Bills you make today will show up here.",
    "close.carry": "Carry over to tomorrow: stock left becomes tomorrow's opening stock when no purchase is entered.",
    "close.wa_send": "Send summary on WhatsApp",
    "close.print_pdf": "Print / PDF",
    # --- board / tags PDFs ---
    "board.item": "Item",
    "board.price": "Price",
    "board.per": "per {per}",
    "board.sold_out": "Sold out",
    "board.scan": "Scan for the live price list · {url}",
    "tags.today": "Today, {at}",
    # --- bill PDF ---
    "bpdf.bill": "Bill {id}",
    "bpdf.customer": "Customer",
    "bpdf.item": "Item",
    "bpdf.qty": "Qty",
    "bpdf.amount": "Amount",
    "bpdf.per": "per {amount} {unit}",
    "bpdf.total": "Total",
    "bpdf.thanks": "Thank you, come again!",
    "bpdf.note": "Prices from {shop}'s list.",
    # --- close PDF ---
    "cpdf.sales_bills": "Sales ({n} bills)",
    # --- error pages ---
    "error.try_samples": "Try the sample shops",
    "error.back_home": "Back home",
    "error.too_many_title": "Too many uploads",
    "error.budget_title": "Demo budget used up",
    "error.file_big_title": "File too big",
    "error.no_photo_title": "No photo chosen",
    "error.photo_big_title": "Photo too big",
    "error.not_photo_title": "Not a photo",
    "error.empty_rec_title": "Empty recording",
    "error.which_item_title": "Which item?",
    "error.unknown_action_title": "Unknown action",
    "error.not_on_list_title": "Not on your list",
    "error.count_wrong_title": "Count does not look right",
    "error.no_count_title": "No count yet",
    # --- WhatsApp texts ---
    "wa.bill_header": "Bill {id} from {shop}",
    "wa.bill_line": "{name} {qty} {unit} - Rs.{total}",
    "wa.bill_soldout": "{name} - sold out",
    "wa.bill_not_on_list": "{name} - not on list",
    "wa.bill_total": "Total: Rs.{total}",
    "wa.quote_header": "Quote from {shop}",
    "wa.quote_total": "Total: Rs.{total}",
    "wa.quote_link": "Quote: {url}",
    "wa.summary_main": "{date}: Sales {sales} (Cash {cash}, UPI {upi}), {bills} bills.",
    "wa.summary_top": "Top: {items}.",
    "wa.summary_top_item": "{label} {qty}{unit} ({amount})",
    "wa.summary_margin": "Margin {margin}.",
    "wa.order_ready": "Your order from {shop} is ready for pickup. Total Rs.{total}.",
    "wa.link_self": "My MarketMate seller link (keep this safe): {url}",
}


_TAMIL: dict[str, str] = {
    # --- customer shop / quote (Task 29, kept) ---
    "prices_set_by_seller": "விற்பனையாளர் நிர்ணயித்த விலைகள்",
    "spoken_and_checked": "பேசி சரிபார்க்கப்பட்டது",
    "get_quote": "விலை மதிப்பீடு பெறுக",
    "call": "அழைக்கவும்",
    "whatsapp": "வாட்ஸ்அப்",
    "sold_out": "விற்றுத் தீர்ந்தது",
    "no_prices": "இன்னும் விலைகள் வெளியிடப்படவில்லை.",
    "quote_subtitle": "{shop} பட்டியல் விலைகள் · {rel} நிர்ணயம்",
    "check_quantity": "அளவை சரிபார்க்கவும்",
    "per": "per",
    "update_quote": "மதிப்பீட்டைப் புதுப்பிக்கவும்",
    "total": "மொத்தம்",
    "your_total": "உங்கள் மொத்தம்",
    "no_prices_title": "இந்தக் கடை இன்றைய விலைகளை இன்னும் பகிரவில்லை",
    "priced": "விலையிடப்பட்டது",
    "not_priced": "விலையிடப்படவில்லை",
    "not_on_list": "இந்தக் கடைப் பட்டியலில் இல்லை",
    "send_whatsapp": "வாட்ஸ்அப்பில் அனுப்புக",
    "pdf": "PDF",
    "back_to": "திரும்புக",
    "no_items": "இந்த மதிப்பீட்டில் பொருட்கள் இல்லை.",
    "speak_list": "பட்டியலைப் பேசுங்கள்",
    "speak_help": "உங்களுக்கு என்ன வேண்டும் என்று சொல்லுங்கள், எ.கா. “2 கிலோ தக்காளி, 1 டஜன் வாழைப்பழம்”.",
    "speak": "பேசுக",
    "stop": "நிறுத்து",
    "tap_speak": "பேசுக என்பதைத் தட்டி உங்கள் பட்டியலைச் சொல்லுங்கள்.",
    "upload_recording": "அல்லது பதிவைப் பதிவேற்றுக",
    "upload_and_quote": "பதிவேற்றி மதிப்பீடு பெறுக",
    "type_list": "பட்டியலைத் தட்டச்சு செய்க",
    "what_need": "உங்களுக்கு என்ன வேண்டும்?",
    "get_quote_short": "மதிப்பீடு பெறுக",
    "photo_list": "பட்டியலைப் புகைப்படம் எடுங்கள்",
    "photo_help": "நீங்கள் எடுத்த பொருட்களின் புகைப்படம், அல்லது கையால் எழுதிய பட்டியல்.",
    "choose_photo": "புகைப்படத்தைத் தேர்வு செய்க",
    "upload_photo_quote": "புகைப்படத்தைப் பதிவேற்றி மதிப்பீடு பெறுக",
    # --- topbar / footer (base) ---
    "top.find_prices": "விலை தேடு",
    "top.start_selling": "விற்க தொடங்கு",
    "top.footer": "மார்க்கெட்மேட் · எல்லா விலையும் உங்க வாயால சொன்னதுதான். எதுவும் கற்பனை இல்லை.",
    "top.main_nav": "முக்கியம்",
    "top.lang_label": "மொழி",
    # --- sidebar ---
    "nav.dashboard": "முகப்பு",
    "nav.prices": "விலைகள்",
    "nav.live_prices": "நேரடி விலை",
    "nav.photos": "போட்டோ",
    "nav.bills": "பில்",
    "nav.purchases": "வாங்கியது",
    "nav.close": "நாள் முடி",
    "nav.shop_page": "கடை பக்கம்",
    "nav.settings": "செட்டிங்",
    "nav.seller_label": "விற்பனையாளர்",
    # --- dashboard ---
    "dash.title_suffix": "முகப்பு",
    "dash.test_shop": "சோதனை கடை - மார்க்கெட்டில் தெரியாது, 7 நாளில் அழியும்",
    "dash.live_pill": "நேரலை · {count} விலை",
    "dash.shop_link": "உங்க கடை லிங்க் · {url}",
    "dash.copy": "நகல்",
    "dash.copied": "நகலெடுத்தாச்சு",
    "dash.share": "பகிர்",
    "dash.qr": "QR",
    "dash.copy_prompt": "உங்க கடை லிங்கை நகலெடுங்கள்:",
    "dash.share_title": "மார்க்கெட்மேட் கடை",
    "dash.live_prices": "நேரடி விலை",
    "dash.live_desc": "கடையை காட்டி ஒவ்வொரு விலையா சொல்லுங்க. பேசப் பேச அட்டை வரும்.",
    "dash.go_live": "நேரலையில் சொல்லு",
    "dash.upload_label": "அல்லது கடை வீடியோவை போடுங்க",
    "dash.upload_help": "3 நிமிஷம் வரை. விலை சொல்லும்போதே அதை காட்டுங்க.",
    "dash.cancel_upload": "பதிவேற்றத்தை நிறுத்து",
    "dash.upload_video": "வீடியோ போடு",
    "dash.upload_progress": "பதிவேற்றம்",
    "dash.tile_update": "குரலில் மாற்று",
    "dash.tile_scan": "ஸ்டாக் போட்டோ",
    "dash.tile_bills": "பில்",
    "dash.tile_bills_sub": "இன்று {sales} · {waiting} காத்திருக்கு",
    "dash.tile_purchases": "வாங்கியது",
    "dash.tile_purchases_sub": "இன்று செலவு {spent}",
    "dash.tile_print_board": "போர்டு அச்சு",
    "dash.tile_print_tags": "விலை சீட்டு அச்சு",
    "dash.tile_export_csv": "CSV எடு",
    "dash.tile_posapp_csv": "POS-app CSV",
    "dash.stock_total": "ஸ்டாக் {total} (பதிப்பு {vid})",
    "dash.stock_left_out": "எண்ணலை: {items}",
    "dash.todays_list": "இன்றைய பட்டியல்",
    "dash.edit": "மாற்று",
    "dash.sold_out": "தீர்ந்தது",
    "dash.back_in_stock": "மீண்டும் வந்தது",
    "dash.per": "/ {per}",
    "dash.stock_line": "ஸ்டாக்: சுமார் {qty} ({source})",
    "dash.no_prices_title": "இன்னும் விலை இல்லை",
    "dash.no_prices_text": "இன்றைய விலையை சொல்லி முதல் பட்டியலை போடுங்க.",
    "dash.recent_sessions": "சமீபத்திய பதிவுகள்",
    "dash.session": "பதிவு {id}",
    "dash.no_uploads": "இன்னும் எதுவும் போடலை.",
    "dash.versions": "பதிப்புகள்",
    "dash.version": "பதிப்பு {id}",
    "dash.published": "வெளியிட்டாச்சு",
    "dash.unpublish": "எடுத்துவிடு",
    "dash.publish": "வெளியிடு",
    "dash.no_versions": "இன்னும் சரிபார்த்த பட்டியல் இல்லை.",
    # --- session / processing ---
    "sess.title": "பதிவு {id}",
    "sess.failed_title": "ஏதோ தப்பாச்சு",
    "sess.try_again": "மீண்டும் முயற்சி",
    "sess.back_dashboard": "முகப்புக்கு போ",
    "sess.approved_text": "சரி ✓ — விலை பட்டியல் சேமிச்சாச்சு.",
    "sess.back_shop": "கடைக்கு போ",
    "sess.voice_waiting": "இந்த மாற்றங்கள் உறுதி பக்கத்தில் காத்திருக்கு. மூடிட்டா மீண்டும் சொல்லுங்க.",
    "sess.update_by_voice": "குரலில் விலை மாற்று",
    "sess.working_photo": "போட்டோவை பார்க்கிறோம்…",
    "sess.working_board": "போர்டை படிக்கிறோம்…",
    "sess.working_purchases": "வாங்கியதை பார்க்கிறோம்…",
    "sess.working_video": "வீடியோவை பார்க்கிறோம்…",
    "sess.step_of": "{total}இல் {step}ஆம் படி",
    "sess.elapsed_s": "ஆன நேரம்: {s} வினாடி",
    "sess.elapsed_m": "ஆன நேரம்: {m} நிமிஷம் {s} வினாடி",
    "sess.refresh_note": "வேலை நடக்குது… 3 வினாடிக்கு ஒருமுறை புதுப்பிக்கும்.",
    "sess.making_bill": "பில் போடுறோம்…",
    "sess.making_bill_title": "பில் போடுறோம் — {shop}",
    "sess.back_bills": "பில்களுக்கு போ",
    # --- stages (labels) ---
    "stage.video.uploaded": "வீடியோ வந்தது",
    "stage.video.audio": "சத்தம் எடுக்கிறோம்",
    "stage.video.listening": "விலையை கேட்கிறோம்",
    "stage.video.items": "சாமான் தேடுறோம்",
    "stage.video.photos": "ஒவ்வொனுக்கும் போட்டோ",
    "stage.video.checking": "ஒவ்வொரு விலையும் சரிபார்ப்பு",
    "stage.video.ready": "சரிபார்க்க தயார்",
    "stage.photo.uploaded": "போட்டோ வந்தது",
    "stage.photo.looking": "போட்டோவை பார்க்கிறோம்",
    "stage.photo.counting": "ஒவ்வொனா எண்ணுறோம்",
    "stage.photo.suggesting": "யோசனை தயார்",
    "stage.photo.ready": "சரிபார்க்க தயார்",
    "stage.quote.received": "கேட்டது வந்தது",
    "stage.quote.listening": "கேட்கிறோம்",
    "stage.quote.looking": "பார்க்கிறோம்",
    "stage.quote.matching": "விலை பொருத்துறோம்",
    "stage.quote.ready": "கணக்கு தயார்",
    "stage.live.listening": "நேரலையில் கேட்கிறோம்",
    "stage.live.items": "சாமான் தேடுறோம்",
    "stage.live.checking": "விலை சரிபார்ப்பு",
    "stage.live.ready": "சரிபார்க்க தயார்",
    "stage.board.uploaded": "போட்டோ வந்தது",
    "stage.board.looking": "போர்டு படிக்கிறோம்",
    "stage.board.items": "சாமான் தேடுறோம்",
    "stage.board.checking": "விலை சரிபார்ப்பு",
    "stage.board.ready": "சரிபார்க்க தயார்",
    "stage.purchase.uploaded": "பதிவு வந்தது",
    "stage.purchase.listening": "வாங்கியதை கேட்கிறோம்",
    "stage.purchase.items": "சாமான் தேடுறோம்",
    "stage.purchase.checking": "எண் சரிபார்ப்பு",
    "stage.purchase.ready": "சரிபார்க்க தயார்",
    # --- stages (friendly lines) ---
    "friendly.video.uploaded": "உங்க பதிவு வந்துடுச்சு.",
    "friendly.video.audio": "வீடியோவிலிருந்து சத்தம் எடுக்கிறோம்.",
    "friendly.video.listening": "உங்க பேச்சை எழுத்தாக மாற்றுறோம்.",
    "friendly.video.items": "நீங்க சொன்ன சாமான் விலையை தேடுறோம்.",
    "friendly.video.photos": "ஒவ்வொனுக்கும் போட்டோ எடுக்கிறோம்.",
    "friendly.video.checking": "சொன்னதோடு விலையை ஒப்பிடுறோம்.",
    "friendly.video.ready": "நீங்க பார்க்க தயார்.",
    "friendly.photo.uploaded": "போட்டோ வந்துடுச்சு.",
    "friendly.photo.looking": "போட்டோவை பார்க்கிறோம்.",
    "friendly.photo.counting": "போட்டோவில் எண்ணுறோம்.",
    "friendly.photo.suggesting": "உங்களுக்கு யோசனை தயார்.",
    "friendly.photo.ready": "நீங்க பார்க்க தயார்.",
    "friendly.quote.received": "கேட்டது வந்துடுச்சு.",
    "friendly.quote.listening": "பேச்சை எழுத்தாக மாற்றுறோம்.",
    "friendly.quote.looking": "போட்டோவை படிக்கிறோம்.",
    "friendly.quote.matching": "கடை விலையோடு ஒப்பிடுறோம்.",
    "friendly.quote.ready": "கணக்கு தயார்.",
    "friendly.live.listening": "நேரலையில் விலை கேட்கிறோம்.",
    "friendly.live.items": "சொன்னதை தேடுறோம்.",
    "friendly.live.checking": "சொன்னதோடு ஒப்பிடுறோம்.",
    "friendly.live.ready": "நீங்க பார்க்க தயார்.",
    "friendly.board.uploaded": "போர்டு போட்டோ வந்துடுச்சு.",
    "friendly.board.looking": "போர்டை படிக்கிறோம்.",
    "friendly.board.items": "போர்டில் சாமான் விலை தேடுறோம்.",
    "friendly.board.checking": "போர்டு விலையை சரிபார்க்கிறோம்.",
    "friendly.board.ready": "நீங்க பார்க்க தயார்.",
    "friendly.purchase.uploaded": "பதிவு வந்துடுச்சு.",
    "friendly.purchase.listening": "பேச்சை எழுத்தாக மாற்றுறோம்.",
    "friendly.purchase.items": "வாங்கியதை தேடுறோம்.",
    "friendly.purchase.checking": "சொன்னதோடு எண்ணை ஒப்பிடுறோம்.",
    "friendly.purchase.ready": "நீங்க பார்க்க தயார்.",
    # --- review ---
    "review.title": "சரி பார்க்கவும்",
    "review.counts": "{total}இல் {ok} சரி · {need} உங்களுக்கு",
    "review.counts_aria": "{total}இல் {ok} விலை சரி",
    "review.check_again": "மீண்டும் பார்",
    "review.check_again_title": "பதிவிலிருந்து மீண்டும் சரிபார்",
    "review.needs_you": "நீங்க பாருங்க",
    "review.looks_right": "சரியா இருக்கு",
    "review.read_from_board": "உங்க போர்டிலிருந்து",
    "review.play": "நீங்க சொன்னதை கேளு",
    "review.price": "விலை",
    "review.per": "அளவு",
    "review.unit": "அலகு",
    "review.remove": "✕ நீக்கு",
    "review.remove_aria": "இந்த விலையை நீக்கு",
    "review.quantity": "அளவு",
    "review.edit_note": "கேட்டதிலிருந்து மாற்றினீங்க. சொன்னதை கேட்டு, சரி என்று தட்டுங்க.",
    "review.confirm": "சரி, உறுதி",
    "review.approve": "விலை பட்டியலை ஒப்பு",
    "review.no_price": "விலை இல்லை",
    # --- flags ---
    "flag.sound_alike": "{a}ஆ {b}ஆ சொன்னீங்க?",
    "flag.sound_alike_ta": "{a}ஆ {b}ஆ சொன்னீங்க? ({x}ம் {y}ம் ஒரே மாதிரி கேட்கும்)",
    "flag.sound_alike_hi": "{a}ஆ {b}ஆ சொன்னீங்க? ({x}ம் {y}ம் இந்தியில் ஒரே மாதிரி)",
    "flag.sound_alike_mr": "{a}ஆ {b}ஆ? ({x}ம் {y}ம் மராத்தியில் ஒரே மாதிரி)",
    "flag.sound_alike_bn": "{a}ஆ {b}ஆ? ({x}ம் {y}ம் வங்காளத்தில் ஒரே மாதிரி)",
    "flag.sound_alike_half": "அரை {unit}ஆ 6 {unit}ஆ? (அரையும் ஆறும் ஒரே மாதிரி)",
    "flag.sound_alike_zh": "டஜனா கட்டா? ({x}ம் {y}ம் சீனத்தில் ஒரே மாதிரி)",
    "flag.sound_alike_th": "டஜனா கிலோவா? ({x}ம் {y}ம் தாய்லாந்தில் ஒரே மாதிரி)",
    "flag.matches_previous": "{price} முந்தைய விலையோடு சரி ({rate} / {unit})",
    "flag.not_heard_price": "{price} விலை பேச்சில் இல்லை",
    "flag.not_heard_qty": "{qty} அளவு பேச்சில் இல்லை",
    "flag.not_heard_total": "{total} மொத்தம் பேச்சில் இல்லை",
    "flag.number_check": "இந்த எண் சந்தேகம் - கேட்டு பாருங்க",
    "flag.unit_missing": "விலைக்கு அலகு இல்லை",
    "flag.unit_missing_qty": "அளவுக்கு அலகு இல்லை",
    "flag.unit_odd": "எடையில் விற்பதுதானே - துண்டு சரியா?",
    "flag.unit_check": "அலகை பாருங்க",
    "flag.unit_from_earlier": "பழைய விலையிலிருந்து அலகு",
    "flag.jump": "விலை {old}லிருந்து {current}க்கு தாவியிருக்கு / {unit} (பழையது)",
    "flag.range": "வரம்பு சொன்னீங்க, ஒரு எண் தேர்வு",
    "flag.two_prices": "ஒரே அளவுக்கு இரண்டு விலை",
    "flag.no_price": "விலையே இல்லை",
    "flag.no_total": "மொத்தம் கேட்கலை",
    "flag.qty_missing": "அளவு இல்லை",
    "flag.qty_missing_heard": "அளவு கேட்கலை",
    "flag.correction": "மாற்றி சொன்னீங்க (\"{marker}\")",
    "flag.unclear_number": "\"{before}\" என்ன எண் என்று தெரியலை",
    "flag.board_confirm": "போர்டிலிருந்து எடுத்தது – தட்டி உறுதி செய்",
    "flag.not_read": "{name} போர்டில் தெரியலை – விலையை எழுதுங்க",
    "flag.new_item": "{name} இப்போதைய பட்டியலில் இல்லை",
    # --- voice update ---
    "upd.confirm_title": "விலை மாற்றத்தை உறுதி செய்",
    "upd.record_title": "இன்றைய விலை சொல்லுங்கள்",
    "upd.heard": "கேட்டது: {transcript}",
    "upd.sold_out_was": "தீர்ந்தது — முன்பு {summary}",
    "upd.back_in_stock": "மீண்டும் வந்தது — {summary}",
    "upd.no_changes": "மாற்றம் எதுவும் கேட்கலை.",
    "upd.confirm_publish": "உறுதி செய்து வெளியிடு",
    "upd.say_changes": "இன்றைய மாற்றத்தை சொல்லுங்க, எ.கா. “தக்காளி 22, வெங்காயம் தீர்ந்தது”. வீடியோ வேண்டாம்.",
    "upd.say_price_for": "{hint} விலையை சொல்லுங்க — எ.கா. “{hint} கிலோ 20 ரூபா”.",
    "upd.start_rec": "பதிவை தொடங்கு",
    "upd.stop_check": "நிறுத்தி பார்",
    "upd.tap_start": "தொடங்கு என்று தட்டி புது விலையை சொல்லுங்க.",
    "upd.upload_rec": "அல்லது பதிவை போடுங்க",
    "upd.upload_check": "போட்டு பார்",
    "upd.board_title": "விலை போர்டு போட்டோ",
    "upd.board_desc": "கையால் எழுதிய அல்லது அச்சு போர்டை போட்டோ எடுங்க. ஒவ்வொரு விலையையும் நீங்க தட்டி சரி செய்த பிறகுதான் வெளியாகும்.",
    "upd.board_choose": "போர்டு போட்டோவை தேர்வு",
    "upd.board_upload": "போர்டை போட்டு பார்",
    "upd.current_prices": "இப்போதைய விலை",
    "upd.sold_out_label": "தீர்ந்தது",
    "upd.price_line": "{price} / {amount} {unit}",
    "upd.no_list": "இன்னும் பட்டியல் இல்லை — முதலில் வீடியோ போடுங்க.",
    "upd.action_set_price": "புது விலை",
    "upd.action_sold_out": "தீர்ந்தது",
    "upd.action_in_stock": "மீண்டும் வந்தது",
    "upd.action_set_qty": "புது அளவு",
    # --- live ---
    "live.title": "நேரடி விலை — {shop}",
    "live.live": "நேரலை",
    "live.camera_preview": "கேமரா",
    "live.start_aria": "நேரடி விலையை தொடங்கு",
    "live.tap_start": "தட்டி தொடங்குங்க. கடையை காட்டி விலையை சொல்லுங்க.",
    "live.finishing": "முடிக்கிறோம்… விலை சரிபார்ப்பு",
    "live.ready": "தயார்",
    "live.finishing_live": "முடிக்கிறோம் – விலை சரிபார்ப்பு…",
    "live.upload_instead": "வீடியோ போடுங்க",
    "live.heard": "கேட்ட விலை",
    "live.no_prices": "இன்னும் விலை இல்லை — பேசுங்க.",
    "live.no_support": "நேரலைக்கு கேமரா மைக் வேண்டும். வீடியோ போடலாம்.",
    "live.video_label": "கடை வீடியோ",
    "live.video_help": "3 நிமிஷம் வரை. சொல்லும்போதே காட்டுங்க.",
    "live.back": "முகப்புக்கு போ",
    # --- photos list ---
    "pho.title": "ஸ்டாக் போட்டோ — {shop}",
    "pho.heading": "ஸ்டாக் போட்டோ",
    "pho.sub": "{shop} · எண்ணிக்கை மதிப்பீடுதான், விலை உங்க வாயால்தான்",
    "pho.scan_title": "ஸ்டாக் போட்டோவை பார்",
    "pho.scan_desc": "கூடை அல்லது குவியலை போட்டோ எடுங்க. தெரிவதை எண்ணுறோம். விலை நீங்க சொன்னாதான்.",
    "pho.drop_camera": "நல்ல வெளிச்சத்தில் ஒரு கூடையை காட்டுங்க.",
    "pho.choose": "போட்டோ தேர்வு",
    "pho.scan_btn": "இதை பார்",
    "pho.gallery_label": "அல்லது கேலரியிலிருந்து",
    "pho.gallery_btn": "கேலரியிலிருந்து போடு",
    "pho.past": "பழைய பார்வைகள்",
    "pho.empty_title": "இன்னும் போட்டோ பார்க்கலை",
    "pho.empty_text": "மேலே முதல் போட்டோவை போடுங்க.",
    # --- photo result ---
    "phr.title": "போட்டோ பார்வை — {shop}",
    "phr.back": "← எல்லா பார்வையும்",
    "phr.heading": "போட்டோ பார்வை",
    "phr.sub": "{shop} · {rel}",
    "phr.scanned_alt": "ஸ்டாக் போட்டோ",
    "phr.counted_aria": "எண்ணியது",
    "phr.show_boxes": "கட்டம் காட்டு",
    "phr.what_we_see": "என்ன தெரியுது",
    "phr.sold_by_weight": "எடையில் விற்பனை - எண்ணிக்கை இல்லை",
    "phr.count_less": "ஒன்று குறை",
    "phr.count_more": "ஒன்று கூட",
    "phr.count_for": "{display} எண்ணிக்கை",
    "phr.suggestions": "யோசனைகள்",
    "phr.no_suggestions": "இதுக்கு யோசனை இல்லை.",
    "phr.notes": "உங்களுக்கு குறிப்பு",
    "phr.seller_only": "உங்களுக்கு மட்டும்: {name} — {note}",
    "phr.honesty": "எண்ணிக்கை மதிப்பீடுதான். விலை நீங்க சொன்னாதான்.",
    "phr.count_about": "சுமார் {n} தெரியுது",
    "phr.count_range": "{a} முதல் {b} வரை - பாருங்க",
    "phr.count_about_check": "சுமார் {n} - சில மறைந்திருக்கலாம், பாருங்க",
    "phr.sugg_retake": "போட்டோ {quality}யா இருக்கு. நெருக்கி நல்ல வெளிச்சத்தில் எடுங்க.",
    "phr.sugg_add_price": "{name} பட்டியலில் இல்லை. விலையை சொல்லி சேருங்க.",
    "phr.sugg_back": "{name} போட்டோவில் இருக்கு ஆனா தீர்ந்ததுனு இருக்கு. மீண்டும் விற்கவா?",
    "phr.sugg_check_count": "{name}: {low} முதல் {high} வரை எண்ணினோம். பாருங்க.",
    "phr.sugg_set_stock": "சுமார் {count} {name} தெரியுது. இன்றைய ஸ்டாக்கா வைக்கவா?",
    "phr.btn_save_stock": "ஸ்டாக் வை",
    "phr.btn_back_sale": "மீண்டும் விற்",
    "phr.btn_say_price": "விலையை சொல்லு",
    "phr.btn_retake": "மீண்டும் எடு",
    "phr.quality_dark": "இருட்டா",
    "phr.quality_blurry": "மங்கலா",
    "phr.quality_far": "தூரமா",
    # --- bills dashboard ---
    "bills.title": "பில் — {shop}",
    "bills.heading": "பில்",
    "bills.sub": "{shop} · இன்றைய விற்பனை",
    "bills.today": "இன்று",
    "bills.yesterday": "நேற்று",
    "bills.week": "7 நாள்",
    "bills.bills_today": "இன்றைய பில்",
    "bills.billed_paid": "போட்டது + வசூல்",
    "bills.sales_today": "இன்றைய விற்பனை",
    "bills.total_billed": "மொத்த பில்",
    "bills.quotes_waiting": "காத்திருக்கும் கணக்கு",
    "bills.from_customers": "வாடிக்கையாளரிடமிருந்து",
    "bills.avg_bill": "சராசரி பில்",
    "bills.per_bill": "இன்று ஒரு பில்லுக்கு",
    "bills.cash": "ரொக்கம்",
    "bills.paid_today": "இன்று வசூல்",
    "bills.upi": "UPI",
    "bills.card": "கார்டு",
    "bills.new_bill": "புது பில்",
    "bills.filter_all": "எல்லாம்",
    "bills.filter_waiting": "காத்திருப்பு",
    "bills.filter_billed": "பில் போட்டது",
    "bills.filter_paid": "வசூலானது",
    "bills.item_one": "{count} சாமான்",
    "bills.item_many": "{count} சாமான்",
    "bills.walk_in": "நேரடி",
    "bills.time_yesterday": "நேற்று {clock}",
    "bills.pill_quote": "கணக்கு",
    "bills.pill_billed": "பில்",
    "bills.pill_paid": "வசூல்",
    "bills.pill_cancelled": "ரத்து",
    "bills.empty_title": "இங்கு பில் இல்லை",
    "bills.empty_text": "இன்று போடும் பில் இங்கு வரும். புது பில்லை தட்டுங்க.",
    "bills.top_today": "இன்று நல்லா போனது",
    "bills.sold": "{qty} {unit} விற்றது",
    "bills.share_sales": "{display} விற்பனை பங்கு",
    "bills.nothing_title": "இன்னும் பில் இல்லை",
    "bills.nothing_text": "இன்று பில் போட்டதும் நல்லா போவது இங்கு தெரியும்.",
    "bills.exports": "வெளியே எடு",
    "bills.date_range": "தேதி",
    "bills.month": "இந்த மாதம்",
    "bills.custom": "தேர்வு",
    "bills.from": "முதல்",
    "bills.to": "வரை",
    "bills.excel": "Excel (.xlsx)",
    "bills.pos_csv": "POS CSV",
    "bills.pricelist_csv": "விலை பட்டியல் CSV",
    "bills.date_aria": "தேதி",
    "bills.filter_aria": "பில் வடிகட்டு",
    # --- bill page ---
    "bill.title": "பில் {id} — {shop}",
    "bill.back": "← எல்லா பில்லும்",
    "bill.heading": "பில் #{id}",
    "bill.receipt_aria": "பில் ரசீது",
    "bill.check_qty": "அளவை பார்",
    "bill.round_off": "சில்லரை {off}",
    "bill.exact": "சரியா {exact}",
    "bill.update": "பில்லை மாற்று",
    "bill.remove": "{display} நீக்கு",
    "bill.no_items": "இந்த பில்லில் எதுவும் இல்லை. கீழே சேருங்க.",
    "bill.accept_quote": "கணக்கை ஏற்றுக்கொள்",
    "bill.collect": "பணம் வாங்கு",
    "bill.scan_upi": "ஏதாவது UPIயில் ஸ்கேன் செய்",
    "bill.add_upi": "UPI QRக்கு செட்டிங்கில் UPI ID சேருங்க.",
    "bill.paid_cash": "ரொக்கம் வசூல்",
    "bill.paid_upi": "UPI வசூல்",
    "bill.paid_card": "கார்டு வசூல்",
    "bill.cash_helper": "சில்லரை உதவி",
    "bill.customer_gave": "கொடுத்தது",
    "bill.exact_chip": "சரியா",
    "bill.give_back": "திருப்பி கொடு {amount}",
    "bill.paid_state": "வசூலாச்சு",
    "bill.paid_by": "{mode}யில் வசூல்",
    "bill.scan_title": "பில் வாங்க ஸ்கேன் செய்யலாம்",
    "bill.share_wa": "வாட்ஸ்அப்பில் அனுப்பு",
    "bill.print_pdf": "அச்சு / PDF",
    "bill.cust_phone": "வாடிக்கையாளர் போன்",
    "bill.wa_number": "ரசீதுக்கு வாட்ஸ்அப் எண்",
    "bill.walkin_help": "நேரடி ஆளுக்கு காலியா விடுங்க.",
    "bill.save_phone": "போனை வை",
    "bill.add_item": "சாமான் சேர்",
    "bill.from_list": "இன்றைய பட்டியலிலிருந்து",
    "bill.add_btn": "சேர்",
    "bill.no_pricelist": "பட்டியல் இல்லை.",
    "bill.not_on_list": "இந்த கடை பட்டியலில் இல்லை",
    "bill.less_aria": "{display} ஒன்று குறை",
    "bill.more_aria": "{display} ஒன்று கூட",
    "bill.qty_aria": "{display} அளவு",
    "bill.weight_chip": "⌨ எடை",
    "bill.weight_aria": "{display} எடையை எழுது",
    "bill.amount_chip": "₹ தொகை",
    "bill.amount_aria": "{display} ரூபாயை போடு",
    "bill.cancel": "வேண்டாம்",
    "bill.ok": "சரி",
    "bill.sold_out": "தீர்ந்தது",
    "bill.no_price_yet": "விலை இல்லை",
    # --- new bill ---
    "bn.title": "புது பில் — {shop}",
    "bn.back": "← எல்லா பில்லும்",
    "bn.heading": "புது பில்",
    "bn.sub": "{shop} · இன்றைய விலையில்",
    "bn.method_aria": "பில் முறை",
    "bn.tap": "தட்டி போடு",
    "bn.speak": "பேசு",
    "bn.type": "எழுது",
    "bn.photo": "போட்டோ",
    "bn.tap_desc": "சீக்கிரம்: ஒவ்வொனுக்கும் + தட்டுங்க. கணக்கு உங்க பட்டியலிலிருந்து.",
    "bn.pick_items": "+ தட்டி தேர்வு",
    "bn.make_bill": "பில் போடு",
    "bn.no_list": "பட்டியல் இல்லை. முதலில் இன்றைய விலையை சொல்லுங்க.",
    "bn.speak_title": "ஆர்டரை சொல்லு",
    "bn.speak_desc": "ஆர்டரை சொல்லுங்க, எ.கா. “2 கிலோ தக்காளி, 1 டஜன் வாழை”.",
    "bn.live_start_aria": "நேரடி பில்லை தொடங்கு",
    "bn.live_hint": "தட்டி தொடங்குங்க. பேசப் பேச வரும்.",
    "bn.bill_so_far": "இதுவரை பில்",
    "bn.total_label": "மொத்தம்:",
    "bn.done": "முடிஞ்சது",
    "bn.upload_instead": "பதிவை போடு",
    "bn.speak_label": "பேசு",
    "bn.stop": "நிறுத்து",
    "bn.tap_speak_order": "பேசு என்று தட்டி ஆர்டரை சொல்லுங்க.",
    "bn.or_upload": "அல்லது பதிவை போடுங்க",
    "bn.choose_rec": "பதிவை தேர்வு",
    "bn.upload_bill": "போட்டு பில் போடு",
    "bn.type_title": "எழுதுங்க",
    "bn.what_took": "என்ன வாங்கினாங்க?",
    "bn.type_placeholder": "2 கிலோ தக்காளி, 1 டஜன் வாழை",
    "bn.photo_title": "கூடையை போட்டோ எடு",
    "bn.photo_desc": "வாடிக்கையாளர் கூடை போட்டோ. எண்ணி உங்க விலையில் போடுறோம்.",
    "bn.photo_choose_label": "கூடை போட்டோவை தேர்வு",
    "bn.photo_choose": "போட்டோ தேர்வு",
    "bn.photo_btn": "போட்டோ போட்டு பில் போடு",
    # --- settings ---
    "set.title": "செட்டிங் — {shop}",
    "set.heading": "செட்டிங்",
    "set.sub": "{shop} · உங்க கடை, உங்க வழி",
    "set.profile": "கடை விவரம்",
    "set.name": "கடை பெயர்",
    "set.area": "இடம்",
    "set.phone": "போன் / வாட்ஸ்அப்",
    "set.phone_help": "7–15 எண், + போடலாம்.",
    "set.language": "மொழி",
    "set.lang_help": "எந்த மொழியில் விலை சொல்வீங்க.",
    "set.currency": "நாணயம்",
    "set.type": "கடை வகை",
    "set.upi": "UPI ID",
    "set.upi_help": "விருப்பம். UPI QRக்கு வேண்டும்.",
    "set.payee": "UPI பெயர்",
    "set.payee_help": "வாடிக்கையாளர் UPIயில் தெரியும். இல்லைனா கடை பெயர்.",
    "set.round": "பில்லை ரூபாய்க்கு முழுதாக்கு",
    "set.round_help": "மொத்தம் முழு ரூபாய்; சில்லரை பில்லில் தெரியும்.",
    "set.save": "சேமி",
    "set.seller_link": "உங்க விற்பனை லிங்க்",
    "set.seller_desc": "எந்த போனிலிருந்தும் முகப்பு, பில், விலையை திறங்க.",
    "set.keep_private": "இதை ரகசியமா வையுங்க: இருந்தா விலையை மாற்றலாம்.",
    "set.copy_prompt": "விற்பனை லிங்கை நகலெடுங்க:",
    "dash.install_app": "ஆப் நிறுவு",
    "dash.install_hint": "ஒரே தட்டில் பில் போட MarketMate-ஐ முகப்புத் திரையில் சேருங்கள்.",
    "dash.install_ios": "iPhone-இல்: Share → Add to Home Screen.",
    "dash.send_link_wa": "என் லிங்க்கை என் WhatsApp-க்கு அனுப்பு",
    "dash.keep_safe": "பத்திரமாக வை",
    "bills.filter_packing": "பேக்கிங்",
    "bills.filter_ready": "தயார்",
    "bills.filter_collected": "எடுத்தாச்சு",
    "bills.pill_packing": "பேக்கிங்",
    "bills.pill_ready": "தயார்",
    "bills.pill_collected": "எடுத்தாச்சு",
    "bill.start_packing": "கட்டத் தொடங்கு",
    "bill.mark_ready": "எடுக்கத் தயார்",
    "bill.mark_collected": "எடுத்தாச்சு",
    "bill.cancel_order": "ஆர்டரை ரத்து செய்",
    "bill.tell_whatsapp": "வாடிக்கையாளருக்கு WhatsApp-இல் சொல்",
    "bill.price_changed": "நீங்கள் offline-இல் இருந்தபோது விலை மாறிவிட்டது — வசூலிக்குமுன் ஒவ்வொரு வரியையும் சரிபாருங்கள்.",
    "bill.made_by": "{name} போட்ட பில்",
    "bill.order_status": "ஆர்டர் நிலை",
    "set.add_helper": "உதவியாளர் சேர்",
    "set.helper_name": "உதவியாளர் பெயர்",
    "set.helper_desc": "உதவியாளர்கள் பில் மட்டுமே போடலாம். விலை, போட்டோ, கொள்முதல், அமைப்புகள், ஏற்றுமதி, நாள் முடிவை மாற்ற முடியாது.",
    "set.helper_once": "இந்த லிங்க்கை இப்போதே பகிருங்கள் — மீண்டும் காட்டப்படாது.",
    "set.helper_remove": "நீக்கு",
    "set.no_helpers": "உதவியாளர்கள் இல்லை.",
    "set.send_link_wa": "என் லிங்க்கை என் WhatsApp-க்கு அனுப்பு",
    "set.keep_safe": "பத்திரமாக வை",
    "set.keep_safe_desc": "இந்த அட்டையை அச்சிட்டு கடையில் வையுங்கள். இந்த லிங்க் உள்ளவர் உங்கள் கடையை இயக்கலாம்.",
    "set.print_card": "பாதுகாப்பு அட்டையை அச்சிடு",
    "error.helper_title": "உதவியாளர்கள் பில் மட்டுமே போடலாம்",
    "error.helper_message": "இந்தப் பக்கம் உங்கள் கடையை மாற்றும், அதனால் உதவியாளர்கள் திறக்க முடியாது. கடை உரிமையாளரைக் கேளுங்கள்.",
    "order.step_new": "ஆர்டர் வந்தது",
    "order.step_packing": "உங்கள் ஆர்டர் கட்டப்படுகிறது",
    "order.step_ready": "எடுக்கத் தயார்",
    "order.step_collected": "எடுத்தாச்சு",
    "order.step_cancelled": "ரத்தானது",
    "order.status_label": "ஆர்டர் நிலை",
    # --- purchases ---
    "pur.title": "வாங்கியது — {shop}",
    "pur.heading": "இன்று வாங்கியது",
    "pur.sub": "{shop} · {today} · இன்று செலவு {spent}",
    "pur.say_title": "வாங்கியதை சொல்லு",
    "pur.say_desc": "எ.கா. “வெங்காயம் 50 கிலோ 1200 ரூபா”. ஒவ்வொரு எண்ணும் கேட்கணும்.",
    "pur.upload_label": "பதிவை போடுங்க",
    "pur.upload_check": "போட்டு பார்",
    "pur.type_title": "ஒரு வரி எழுது",
    "pur.item": "சாமான்",
    "pur.qty": "அளவு",
    "pur.unit": "அலகு",
    "pur.total_paid": "மொத்தம் கொடுத்தது",
    "pur.add": "சேர்",
    "pur.bought_today": "இன்று வாங்கியது",
    "pur.paid_cost": "கொடுத்தது {total} · அடக்கம் {cost}",
    "pur.stock_left": "மீதி ஸ்டாக்: {left}",
    "pur.empty_title": "இன்னும் வாங்கலை",
    "pur.empty_text": "காலையில் மார்க்கெட்டில் வாங்கியதை சொல்லுங்க அல்லது எழுதுங்க.",
    "pur.recent": "சமீபத்திய குரல்",
    "pur.purchase_n": "வாங்கியது {id}",
    "pur.buy": "வாங்கியது",
    "pur.sell": "விற்பனை",
    # --- purchase review ---
    "pr.title": "வாங்கியதை உறுதி செய்",
    "pr.heading": "வாங்கியதை உறுதி செய்",
    "pr.heard": "கேட்டது: {transcript}",
    "pr.qty_total": "{qty} {unit} · மொத்தம் {total}",
    "pr.nothing": "எதுவும் கேட்கலை. மீண்டும் சொல்லுங்க.",
    "pr.confirm_btn": "உறுதி செய்",
    # --- day close ---
    "close.title": "நாள் முடி {day} — {shop}",
    "close.heading": "நாள் முடி",
    "close.sub": "{shop} · {day}",
    "close.day": "நாள்",
    "close.show": "காட்டு",
    "close.sales": "விற்பனை",
    "close.billed_paid": "பில் + வசூல்",
    "close.bills": "பில்",
    "close.spent": "வாங்கிய செலவு",
    "close.market_run": "மார்க்கெட்",
    "close.margin": "லாபம்",
    "close.margin_sub": "விற்பனை - அடக்கம்",
    "close.cash": "ரொக்கம்",
    "close.paid": "வசூல்",
    "close.upi": "UPI",
    "close.card": "கார்டு",
    "close.unpaid": "வசூலாகாதது",
    "close.billed_not_paid": "பில் ஆனா வசூல் இல்லை",
    "close.items_sold": "விற்றது",
    "close.th_item": "சாமான்",
    "close.th_sold": "விற்றது",
    "close.th_sales": "விற்பனை",
    "close.th_opening": "தொடக்கம்",
    "close.th_left": "மீதி",
    "close.th_wastage": "வீண்",
    "close.wastage_aria": "{display} வீண்",
    "close.save_wastage": "வீணை வை",
    "close.nothing_title": "பில் இல்லை",
    "close.nothing_text": "இன்றைய பில் இங்கு வரும்.",
    "close.carry": "நாளைக்கு: மீதி ஸ்டாக் நாளைய தொடக்கமாகும்.",
    "close.wa_send": "வாட்ஸ்அப்பில் அனுப்பு",
    "close.print_pdf": "அச்சு / PDF",
    # --- board / tags PDFs ---
    "board.item": "சாமான்",
    "board.price": "விலை",
    "board.per": "/ {per}",
    "board.sold_out": "தீர்ந்தது",
    "board.scan": "நேரடி விலைக்கு ஸ்கேன் · {url}",
    "tags.today": "இன்று, {at}",
    # --- bill PDF ---
    "bpdf.bill": "பில் {id}",
    "bpdf.customer": "வாடிக்கையாளர்",
    "bpdf.item": "சாமான்",
    "bpdf.qty": "அளவு",
    "bpdf.amount": "தொகை",
    "bpdf.per": "/ {amount} {unit}",
    "bpdf.total": "மொத்தம்",
    "bpdf.thanks": "நன்றி, மீண்டும் வாங்க!",
    "bpdf.note": "{shop} விலை பட்டியலிலிருந்து.",
    # --- close PDF ---
    "cpdf.sales_bills": "விற்பனை ({n} பில்)",
    # --- error pages ---
    "error.try_samples": "மாதிரி கடையை பார்",
    "error.back_home": "முகப்புக்கு போ",
    "error.too_many_title": "அதிகம் போட்டுட்டீங்க",
    "error.budget_title": "பட்ஜெட் தீர்ந்தது",
    "error.file_big_title": "கோப்பு பெரிசு",
    "error.no_photo_title": "போட்டோ தேர்வு இல்லை",
    "error.photo_big_title": "போட்டோ பெரிசு",
    "error.not_photo_title": "போட்டோ இல்லை",
    "error.empty_rec_title": "காலி பதிவு",
    "error.which_item_title": "எந்த சாமான்?",
    "error.unknown_action_title": "தெரியாத செயல்",
    "error.not_on_list_title": "பட்டியலில் இல்லை",
    "error.count_wrong_title": "எண்ணிக்கை சரியில்லை",
    "error.no_count_title": "எண்ணிக்கை இல்லை",
    # --- WhatsApp texts ---
    "wa.bill_header": "{shop} பில் {id}",
    "wa.bill_line": "{name} {qty} {unit} - ரூ.{total}",
    "wa.bill_soldout": "{name} - தீர்ந்தது",
    "wa.bill_not_on_list": "{name} - பட்டியலில் இல்லை",
    "wa.bill_total": "மொத்தம்: ரூ.{total}",
    "wa.quote_header": "{shop} கணக்கு",
    "wa.quote_total": "மொத்தம்: ரூ.{total}",
    "wa.quote_link": "கணக்கு: {url}",
    "wa.summary_main": "{date}: விற்பனை {sales} (ரொக்கம் {cash}, UPI {upi}), {bills} பில்.",
    "wa.summary_top": "நல்லா போனது: {items}.",
    "wa.summary_top_item": "{label} {qty}{unit} ({amount})",
    "wa.summary_margin": "லாபம் {margin}.",
    "wa.order_ready": "{shop} கடையில் உங்கள் ஆர்டர் எடுக்கத் தயார். மொத்தம் ரூ.{total}.",
    "wa.link_self": "என் MarketMate விற்பனை லிங்க் (பத்திரமாக வையுங்கள்): {url}",
}


_HINDI: dict[str, str] = {
    # --- customer shop / quote (Task 29, kept) ---
    "prices_set_by_seller": "विक्रेता द्वारा तय कीमतें",
    "spoken_and_checked": "बोली और जाँची हुई",
    "get_quote": "कीमत अनुमान पाएँ",
    "call": "कॉल करें",
    "whatsapp": "व्हाट्सऐप",
    "sold_out": "समाप्त",
    "no_prices": "अभी कोई कीमत प्रकाशित नहीं हुई।",
    "quote_subtitle": "{shop} की सूची से कीमतें · {rel} निर्धारित",
    "check_quantity": "मात्रा जाँचें",
    "per": "per",
    "update_quote": "अनुमान अपडेट करें",
    "total": "कुल",
    "your_total": "आपका कुल",
    "no_prices_title": "इस दुकान ने आज की कीमतें अभी साझा नहीं की हैं",
    "priced": "कीमत लगी",
    "not_priced": "कीमत नहीं लगी",
    "not_on_list": "इस दुकान की सूची में नहीं है",
    "send_whatsapp": "व्हाट्सऐप पर भेजें",
    "pdf": "PDF",
    "back_to": "वापस जाएँ",
    "no_items": "इस अनुमान में कोई सामान नहीं है।",
    "speak_list": "अपनी सूची बोलें",
    "speak_help": "आपको क्या चाहिए, बोलें, जैसे “2 किलो टमाटर, 1 दर्जन केला”।",
    "speak": "बोलें",
    "stop": "रोकें",
    "tap_speak": "बोलें दबाकर अपनी सूची बोलें।",
    "upload_recording": "या रिकॉर्डिंग अपलोड करें",
    "upload_and_quote": "अपलोड करें और अनुमान पाएँ",
    "type_list": "अपनी सूची लिखें",
    "what_need": "आपको क्या चाहिए?",
    "get_quote_short": "अनुमान पाएँ",
    "photo_list": "सूची की फोटो लें",
    "photo_help": "आपके चुने सामान की फोटो, या हाथ से लिखी सूची।",
    "choose_photo": "फोटो चुनें",
    "upload_photo_quote": "फोटो अपलोड करें और अनुमान पाएँ",
    # --- topbar / footer (base) ---
    "top.find_prices": "दाम खोजें",
    "top.start_selling": "बेचना शुरू करें",
    "top.footer": "मार्केटमेट · हर दाम आपकी बोली से। कुछ अंदाज़ा नहीं।",
    "top.main_nav": "मुख्य",
    "top.lang_label": "भाषा",
    # --- sidebar ---
    "nav.dashboard": "होम",
    "nav.prices": "दाम",
    "nav.live_prices": "लाइव दाम",
    "nav.photos": "फोटो",
    "nav.bills": "बिल",
    "nav.purchases": "खरीद",
    "nav.close": "दिन का हिसाब",
    "nav.shop_page": "दुकान पेज",
    "nav.settings": "सेटिंग",
    "nav.seller_label": "विक्रेता",
    # --- dashboard ---
    "dash.title_suffix": "होम",
    "dash.test_shop": "टेस्ट दुकान - बाज़ार में नहीं दिखेगी, 7 दिन में मिटेगी",
    "dash.live_pill": "लाइव · {count} दाम",
    "dash.shop_link": "आपकी दुकान का लिंक · {url}",
    "dash.copy": "कॉपी",
    "dash.copied": "कॉपी हुआ",
    "dash.share": "शेयर",
    "dash.qr": "QR",
    "dash.copy_prompt": "अपनी दुकान का लिंक कॉपी करें:",
    "dash.share_title": "मार्केटमेट दुकान",
    "dash.live_prices": "लाइव दाम",
    "dash.live_desc": "दुकान दिखाकर हर दाम बोलिए। बोलते ही कार्ड आएगा।",
    "dash.go_live": "लाइव बोलिए",
    "dash.upload_label": "या दुकान का वीडियो डालिए",
    "dash.upload_help": "3 मिनट तक। दाम बोलते हुए सामान दिखाइए।",
    "dash.cancel_upload": "अपलोड रोकिए",
    "dash.upload_video": "वीडियो डालिए",
    "dash.upload_progress": "अपलोड",
    "dash.tile_update": "बोलकर बदलिए",
    "dash.tile_scan": "स्टॉक फोटो",
    "dash.tile_bills": "बिल",
    "dash.tile_bills_sub": "आज {sales} · {waiting} बाकी",
    "dash.tile_purchases": "खरीद",
    "dash.tile_purchases_sub": "आज खर्च {spent}",
    "dash.tile_print_board": "बोर्ड छापिए",
    "dash.tile_print_tags": "दाम पर्ची छापिए",
    "dash.tile_export_csv": "CSV निकालिए",
    "dash.tile_posapp_csv": "POS-app CSV",
    "dash.stock_total": "स्टॉक {total} (संस्करण {vid})",
    "dash.stock_left_out": "गिना नहीं: {items}",
    "dash.todays_list": "आज की सूची",
    "dash.edit": "बदलिए",
    "dash.sold_out": "खत्म",
    "dash.back_in_stock": "वापस आया",
    "dash.per": "/ {per}",
    "dash.stock_line": "स्टॉक: करीब {qty} ({source})",
    "dash.no_prices_title": "अभी दाम नहीं",
    "dash.no_prices_text": "आज के दाम बोलकर पहली सूची बनाइए।",
    "dash.recent_sessions": "हाल की रिकॉर्डिंग",
    "dash.session": "रिकॉर्डिंग {id}",
    "dash.no_uploads": "अभी कुछ नहीं डाला।",
    "dash.versions": "सूचियाँ",
    "dash.version": "सूची {id}",
    "dash.published": "छपा हुआ",
    "dash.unpublish": "हटाइए",
    "dash.publish": "छापिए",
    "dash.no_versions": "अभी कोई जाँची सूची नहीं।",
    # --- session / processing ---
    "sess.title": "रिकॉर्डिंग {id}",
    "sess.failed_title": "कुछ गड़बड़ हुई",
    "sess.try_again": "फिर कोशिश करिए",
    "sess.back_dashboard": "होम जाइए",
    "sess.approved_text": "पक्का ✓ — दाम सूची सहेजी।",
    "sess.back_shop": "दुकान जाइए",
    "sess.voice_waiting": "ये बदलाव पक्के पेज पर रुके हैं। बंद किया तो फिर बोलिए।",
    "sess.update_by_voice": "बोलकर दाम बदलिए",
    "sess.working_photo": "फोटो देख रहे हैं…",
    "sess.working_board": "बोर्ड पढ़ रहे हैं…",
    "sess.working_purchases": "खरीद देख रहे हैं…",
    "sess.working_video": "वीडियो देख रहे हैं…",
    "sess.step_of": "{total} में {step}वाँ कदम",
    "sess.elapsed_s": "समय: {s} सेकंड",
    "sess.elapsed_m": "समय: {m} मिनट {s} सेकंड",
    "sess.refresh_note": "काम चल रहा है… हर 3 सेकंड में ताज़ा होगा।",
    "sess.making_bill": "बिल बना रहे हैं…",
    "sess.making_bill_title": "बिल बन रहा है — {shop}",
    "sess.back_bills": "बिलों पर जाइए",
    # --- stages (labels) ---
    "stage.video.uploaded": "वीडियो आया",
    "stage.video.audio": "आवाज़ निकाल रहे हैं",
    "stage.video.listening": "दाम सुन रहे हैं",
    "stage.video.items": "सामान खोज रहे हैं",
    "stage.video.photos": "हर चीज़ की फोटो",
    "stage.video.checking": "हर दाम जाँच रहे हैं",
    "stage.video.ready": "जाँच को तैयार",
    "stage.photo.uploaded": "फोटो आई",
    "stage.photo.looking": "फोटो देख रहे हैं",
    "stage.photo.counting": "हर चीज़ गिन रहे हैं",
    "stage.photo.suggesting": "सुझाव बना रहे हैं",
    "stage.photo.ready": "जाँच को तैयार",
    "stage.quote.received": "माँग आई",
    "stage.quote.listening": "सुन रहे हैं",
    "stage.quote.looking": "देख रहे हैं",
    "stage.quote.matching": "दाम मिला रहे हैं",
    "stage.quote.ready": "अनुमान तैयार",
    "stage.live.listening": "लाइव सुन रहे हैं",
    "stage.live.items": "सामान खोज रहे हैं",
    "stage.live.checking": "हर दाम जाँच",
    "stage.live.ready": "जाँच को तैयार",
    "stage.board.uploaded": "फोटो आई",
    "stage.board.looking": "बोर्ड पढ़ रहे हैं",
    "stage.board.items": "सामान खोज रहे हैं",
    "stage.board.checking": "हर दाम जाँच",
    "stage.board.ready": "जाँच को तैयार",
    "stage.purchase.uploaded": "रिकॉर्डिंग आई",
    "stage.purchase.listening": "खरीद सुन रहे हैं",
    "stage.purchase.items": "सामान खोज रहे हैं",
    "stage.purchase.checking": "हर संख्या जाँच",
    "stage.purchase.ready": "जाँच को तैयार",
    # --- stages (friendly lines) ---
    "friendly.video.uploaded": "आपकी रिकॉर्डिंग आ गई।",
    "friendly.video.audio": "वीडियो से आवाज़ निकाल रहे हैं।",
    "friendly.video.listening": "आपकी बोली लिख रहे हैं।",
    "friendly.video.items": "आपके बोले सामान-दाम खोज रहे हैं।",
    "friendly.video.photos": "हर चीज़ की फोटो ले रहे हैं।",
    "friendly.video.checking": "बोली से हर दाम मिला रहे हैं।",
    "friendly.video.ready": "आप जाँच लीजिए।",
    "friendly.photo.uploaded": "फोटो आ गई।",
    "friendly.photo.looking": "फोटो देख रहे हैं।",
    "friendly.photo.counting": "फोटो में गिन रहे हैं।",
    "friendly.photo.suggesting": "आपके लिए सुझाव।",
    "friendly.photo.ready": "आप जाँच लीजिए।",
    "friendly.quote.received": "माँग आ गई।",
    "friendly.quote.listening": "बोली लिख रहे हैं।",
    "friendly.quote.looking": "फोटो पढ़ रहे हैं।",
    "friendly.quote.matching": "दुकान के दाम से मिला रहे हैं।",
    "friendly.quote.ready": "अनुमान तैयार।",
    "friendly.live.listening": "लाइव दाम सुन रहे हैं।",
    "friendly.live.items": "बोली खोज रहे हैं।",
    "friendly.live.checking": "बोली से मिला रहे हैं।",
    "friendly.live.ready": "आप जाँच लीजिए।",
    "friendly.board.uploaded": "बोर्ड फोटो आ गई।",
    "friendly.board.looking": "बोर्ड पढ़ रहे हैं।",
    "friendly.board.items": "बोर्ड पर सामान-दाम खोज रहे हैं।",
    "friendly.board.checking": "बोर्ड के दाम जाँच रहे हैं।",
    "friendly.board.ready": "आप जाँच लीजिए।",
    "friendly.purchase.uploaded": "रिकॉर्डिंग आ गई।",
    "friendly.purchase.listening": "बोली लिख रहे हैं।",
    "friendly.purchase.items": "खरीद खोज रहे हैं।",
    "friendly.purchase.checking": "बोली से संख्या मिला रहे हैं।",
    "friendly.purchase.ready": "आप जाँच लीजिए।",
    # --- review ---
    "review.title": "जाँच लें",
    "review.counts": "{total} में {ok} ठीक · {need} आप देखिए",
    "review.counts_aria": "{total} में {ok} दाम ठीक",
    "review.check_again": "फिर जाँचिए",
    "review.check_again_title": "रिकॉर्डिंग से फिर जाँचिए",
    "review.needs_you": "आप देखिए",
    "review.looks_right": "ठीक है",
    "review.read_from_board": "आपके बोर्ड से",
    "review.play": "आपकी बोली सुनिए",
    "review.price": "दाम",
    "review.per": "पर",
    "review.unit": "इकाई",
    "review.remove": "✕ हटाइए",
    "review.remove_aria": "ये दाम हटाइए",
    "review.quantity": "मात्रा",
    "review.edit_note": "सुने से बदल दिया। बोली सुनकर सही पर टिक करिए।",
    "review.confirm": "पक्का",
    "review.approve": "दाम सूची पक्की करिए",
    "review.no_price": "दाम नहीं",
    # --- flags ---
    "flag.sound_alike": "आपने {a} बोला या {b}?",
    "flag.sound_alike_ta": "{a} या {b} बोला? ({x} और {y} तमिल में एक जैसे लगते हैं)",
    "flag.sound_alike_hi": "{a} या {b} बोला? ({x} और {y} एक जैसे लगते हैं)",
    "flag.sound_alike_mr": "{a} या {b}? ({x} और {y} मराठी में एक जैसे)",
    "flag.sound_alike_bn": "{a} या {b}? ({x} और {y} बंगाली में एक जैसे)",
    "flag.sound_alike_half": "आधा {unit} या 6 {unit}? (अरै और आरु एक जैसे)",
    "flag.sound_alike_zh": "दर्जन या गुच्छा? ({x} और {y} चीनी में एक जैसे)",
    "flag.sound_alike_th": "दर्जन या किलो? ({x} और {y} थाई में एक जैसे)",
    "flag.matches_previous": "{price} पहले दाम से मिला ({rate} / {unit})",
    "flag.not_heard_price": "{price} दाम बोली में नहीं",
    "flag.not_heard_qty": "{qty} मात्रा बोली में नहीं",
    "flag.not_heard_total": "{total} कुल बोली में नहीं",
    "flag.number_check": "ये संख्या पक्की नहीं - सुन लीजिए",
    "flag.unit_missing": "दाम की इकाई नहीं",
    "flag.unit_missing_qty": "मात्रा की इकाई नहीं",
    "flag.unit_odd": "वज़न से बिकता है - पीस ठीक है?",
    "flag.unit_check": "इकाई देख लीजिए",
    "flag.unit_from_earlier": "पुराने दाम से इकाई",
    "flag.jump": "दाम {old} से {current} हुआ / {unit} (पुराना)",
    "flag.range": "रेंज बोली, एक संख्या चुनिए",
    "flag.two_prices": "एक मात्रा के दो दाम",
    "flag.no_price": "दाम ही नहीं",
    "flag.no_total": "कुल नहीं सुना",
    "flag.qty_missing": "मात्रा नहीं",
    "flag.qty_missing_heard": "मात्रा नहीं सुनी",
    "flag.correction": "सुधार बोला (\"{marker}\")",
    "flag.unclear_number": "\"{before}\" संख्या साफ नहीं",
    "flag.board_confirm": "बोर्ड से पढ़ा – दबाकर पक्का करिए",
    "flag.not_read": "{name} बोर्ड में नहीं दिखा – दाम लिखिए",
    "flag.new_item": "{name} आज की सूची में नहीं",
    # --- voice update ---
    "upd.confirm_title": "दाम बदलाव पक्का करिए",
    "upd.record_title": "आज के दाम बोलिए",
    "upd.heard": "सुना: {transcript}",
    "upd.sold_out_was": "खत्म — पहले {summary}",
    "upd.back_in_stock": "वापस आया — {summary}",
    "upd.no_changes": "कोई बदलाव नहीं सुना।",
    "upd.confirm_publish": "पक्का करके छापिए",
    "upd.say_changes": "आज के बदलाव बोलिए, जैसे “टमाटर 22, प्याज़ खत्म”। वीडियो नहीं चाहिए।",
    "upd.say_price_for": "{hint} का दाम बोलिए — जैसे “{hint} किलो 20 रुपया”।",
    "upd.start_rec": "रिकॉर्डिंग शुरू करिए",
    "upd.stop_check": "रोककर देखिए",
    "upd.tap_start": "शुरू दबाकर नए दाम बोलिए।",
    "upd.upload_rec": "या रिकॉर्डिंग डालिए",
    "upd.upload_check": "डालकर देखिए",
    "upd.board_title": "दाम बोर्ड की फोटो",
    "upd.board_desc": "हाथ से लिखे या छपे बोर्ड की फोटो लीजिए। हर दाम आप दबाकर पक्का करेंगे, तभी छपेगा।",
    "upd.board_choose": "बोर्ड की फोटो चुनिए",
    "upd.board_upload": "बोर्ड डालकर देखिए",
    "upd.current_prices": "अभी के दाम",
    "upd.sold_out_label": "खत्म",
    "upd.price_line": "{price} / {amount} {unit}",
    "upd.no_list": "अभी सूची नहीं — पहले वीडियो डालिए।",
    "upd.action_set_price": "नया दाम",
    "upd.action_sold_out": "खत्म",
    "upd.action_in_stock": "वापस आया",
    "upd.action_set_qty": "नई मात्रा",
    # --- live ---
    "live.title": "लाइव दाम — {shop}",
    "live.live": "लाइव",
    "live.camera_preview": "कैमरा",
    "live.start_aria": "लाइव दाम शुरू करिए",
    "live.tap_start": "दबाकर शुरू करिए। दुकान दिखाकर दाम बोलिए।",
    "live.finishing": "खत्म कर रहे हैं… दाम जाँच",
    "live.ready": "तैयार",
    "live.finishing_live": "खत्म कर रहे हैं – दाम जाँच…",
    "live.upload_instead": "वीडियो डालिए",
    "live.heard": "सुने दाम",
    "live.no_prices": "अभी दाम नहीं — बोलिए।",
    "live.no_support": "लाइव के लिए कैमरा-माइक चाहिए। वीडियो डाल सकते हैं।",
    "live.video_label": "दुकान का वीडियो",
    "live.video_help": "3 मिनट तक। बोलते हुए दिखाइए।",
    "live.back": "होम जाइए",
    # --- photos list ---
    "pho.title": "स्टॉक फोटो — {shop}",
    "pho.heading": "स्टॉक फोटो",
    "pho.sub": "{shop} · गिनती अंदाज़ा है, दाम आपकी बोली से",
    "pho.scan_title": "स्टॉक फोटो देखिए",
    "pho.scan_desc": "टोकरी या ढेर की फोटो लीजिए। दिखता गिनते हैं। दाम आप बोलेंगे तभी।",
    "pho.drop_camera": "अच्छी रोशनी में एक टोकरी दिखाइए।",
    "pho.choose": "फोटो चुनिए",
    "pho.scan_btn": "ये देखिए",
    "pho.gallery_label": "या गैलरी से",
    "pho.gallery_btn": "गैलरी से डालिए",
    "pho.past": "पुरानी जाँच",
    "pho.empty_title": "अभी फोटो नहीं देखी",
    "pho.empty_text": "ऊपर पहली फोटो डालिए।",
    # --- photo result ---
    "phr.title": "फोटो जाँच — {shop}",
    "phr.back": "← सारी जाँच",
    "phr.heading": "फोटो जाँच",
    "phr.sub": "{shop} · {rel}",
    "phr.scanned_alt": "स्टॉक फोटो",
    "phr.counted_aria": "गिनी चीज़ें",
    "phr.show_boxes": "डिब्बे दिखाइए",
    "phr.what_we_see": "क्या दिखा",
    "phr.sold_by_weight": "वज़न से बिकता - गिनती नहीं",
    "phr.count_less": "एक कम",
    "phr.count_more": "एक ज़्यादा",
    "phr.count_for": "{display} की गिनती",
    "phr.suggestions": "सुझाव",
    "phr.no_suggestions": "इस फोटो के लिए सुझाव नहीं।",
    "phr.notes": "आपके लिए नोट",
    "phr.seller_only": "सिर्फ आपके लिए: {name} — {note}",
    "phr.honesty": "गिनती अंदाज़ा है। दाम आप बोलेंगे तभी।",
    "phr.count_about": "करीब {n} दिखे",
    "phr.count_range": "{a} से {b} तक - देख लीजिए",
    "phr.count_about_check": "करीब {n} - कुछ छिपे होंगे, देख लीजिए",
    "phr.sugg_retake": "फोटो {quality} है। पास से अच्छी रोशनी में लीजिए।",
    "phr.sugg_add_price": "{name} सूची में नहीं। दाम बोलकर जोड़िए।",
    "phr.sugg_back": "{name} फोटो में है पर खत्म लिखा। वापस बेचिए?",
    "phr.sugg_check_count": "{name}: {low} से {high} गिना। देख लीजिए।",
    "phr.sugg_set_stock": "करीब {count} {name} दिखे। आज का स्टॉक रखें?",
    "phr.btn_save_stock": "स्टॉक रखिए",
    "phr.btn_back_sale": "वापस बेचिए",
    "phr.btn_say_price": "दाम बोलिए",
    "phr.btn_retake": "फिर लीजिए",
    "phr.quality_dark": "अँधेरी",
    "phr.quality_blurry": "धुँधली",
    "phr.quality_far": "दूर से",
    # --- bills dashboard ---
    "bills.title": "बिल — {shop}",
    "bills.heading": "बिल",
    "bills.sub": "{shop} · आज की बिक्री",
    "bills.today": "आज",
    "bills.yesterday": "कल",
    "bills.week": "7 दिन",
    "bills.bills_today": "आज के बिल",
    "bills.billed_paid": "बने + वसूल",
    "bills.sales_today": "आज की बिक्री",
    "bills.total_billed": "कुल बिल",
    "bills.quotes_waiting": "रुके अनुमान",
    "bills.from_customers": "ग्राहकों से",
    "bills.avg_bill": "औसत बिल",
    "bills.per_bill": "आज प्रति बिल",
    "bills.cash": "नकद",
    "bills.paid_today": "आज वसूल",
    "bills.upi": "UPI",
    "bills.card": "कार्ड",
    "bills.new_bill": "नया बिल",
    "bills.filter_all": "सब",
    "bills.filter_waiting": "रुके",
    "bills.filter_billed": "बने",
    "bills.filter_paid": "वसूल",
    "bills.item_one": "{count} सामान",
    "bills.item_many": "{count} सामान",
    "bills.walk_in": "सीधे",
    "bills.time_yesterday": "कल {clock}",
    "bills.pill_quote": "अनुमान",
    "bills.pill_billed": "बिल",
    "bills.pill_paid": "वसूल",
    "bills.pill_cancelled": "रद्द",
    "bills.empty_title": "यहाँ बिल नहीं",
    "bills.empty_text": "आज के बिल यहाँ आएँगे। नया बिल दबाइए।",
    "bills.top_today": "आज खूब बिका",
    "bills.sold": "{qty} {unit} बिका",
    "bills.share_sales": "{display} बिक्री हिस्सा",
    "bills.nothing_title": "अभी बिल नहीं",
    "bills.nothing_text": "आज बिल बनते ही खूब बिकने वाला यहाँ दिखेगा।",
    "bills.exports": "निकालिए",
    "bills.date_range": "तारीख",
    "bills.month": "इस महीने",
    "bills.custom": "चुनिए",
    "bills.from": "से",
    "bills.to": "तक",
    "bills.excel": "Excel (.xlsx)",
    "bills.pos_csv": "POS CSV",
    "bills.pricelist_csv": "दाम सूची CSV",
    "bills.date_aria": "तारीख",
    "bills.filter_aria": "बिल छाँटिए",
    # --- bill page ---
    "bill.title": "बिल {id} — {shop}",
    "bill.back": "← सारे बिल",
    "bill.heading": "बिल #{id}",
    "bill.receipt_aria": "बिल रसीद",
    "bill.check_qty": "मात्रा देखिए",
    "bill.round_off": "पूर्णांक {off}",
    "bill.exact": "ठीक {exact}",
    "bill.update": "बिल बदलिए",
    "bill.remove": "{display} हटाइए",
    "bill.no_items": "इस बिल में कुछ नहीं। नीचे जोड़िए।",
    "bill.accept_quote": "अनुमान मानिए",
    "bill.collect": "पैसे लीजिए",
    "bill.scan_upi": "किसी UPI से स्कैन करिए",
    "bill.add_upi": "UPI QR के लिए सेटिंग में UPI ID जोड़िए।",
    "bill.paid_cash": "नकद वसूल",
    "bill.paid_upi": "UPI वसूल",
    "bill.paid_card": "कार्ड वसूल",
    "bill.cash_helper": "नकद मदद",
    "bill.customer_gave": "ग्राहक ने दिया",
    "bill.exact_chip": "ठीक",
    "bill.give_back": "वापस दीजिए {amount}",
    "bill.paid_state": "वसूल",
    "bill.paid_by": "{mode} से वसूल",
    "bill.scan_title": "बिल के लिए स्कैन करिए",
    "bill.share_wa": "व्हाट्सऐप पर भेजिए",
    "bill.print_pdf": "छापिए / PDF",
    "bill.cust_phone": "ग्राहक फोन",
    "bill.wa_number": "रसीद के लिए व्हाट्सऐप नंबर",
    "bill.walkin_help": "सीधे ग्राहक के लिए खाली छोड़िए।",
    "bill.save_phone": "फोन रखिए",
    "bill.add_item": "सामान जोड़िए",
    "bill.from_list": "आज की सूची से",
    "bill.add_btn": "जोड़िए",
    "bill.no_pricelist": "सूची नहीं।",
    "bill.not_on_list": "इस दुकान की सूची में नहीं",
    "bill.less_aria": "{display} एक कम",
    "bill.more_aria": "{display} एक ज़्यादा",
    "bill.qty_aria": "{display} की मात्रा",
    "bill.weight_chip": "⌨ वज़न",
    "bill.weight_aria": "{display} का वज़न लिखिए",
    "bill.amount_chip": "₹ राशि",
    "bill.amount_aria": "{display} की राशि डालिए",
    "bill.cancel": "रद्द करिए",
    "bill.ok": "ठीक",
    "bill.sold_out": "खत्म",
    "bill.no_price_yet": "दाम नहीं",
    # --- new bill ---
    "bn.title": "नया बिल — {shop}",
    "bn.back": "← सारे बिल",
    "bn.heading": "नया बिल",
    "bn.sub": "{shop} · आज के दाम से",
    "bn.method_aria": "बिल तरीका",
    "bn.tap": "दबाकर डालिए",
    "bn.speak": "बोलिए",
    "bn.type": "लिखिए",
    "bn.photo": "फोटो",
    "bn.tap_desc": "सबसे तेज़: हर चीज़ पर + दबाइए। हिसाब आपकी सूची से।",
    "bn.pick_items": "+ दबाकर चुनिए",
    "bn.make_bill": "बिल बनाइए",
    "bn.no_list": "सूची नहीं। पहले आज के दाम बोलिए।",
    "bn.speak_title": "ऑर्डर बोलिए",
    "bn.speak_desc": "ऑर्डर बोलिए, जैसे “2 किलो टमाटर, 1 दर्जन केला”।",
    "bn.live_start_aria": "लाइव बिल शुरू करिए",
    "bn.live_hint": "दबाकर शुरू करिए। बोलते ही आएगा।",
    "bn.bill_so_far": "अब तक बिल",
    "bn.total_label": "कुल:",
    "bn.done": "हो गया",
    "bn.upload_instead": "रिकॉर्डिंग डालिए",
    "bn.speak_label": "बोलिए",
    "bn.stop": "रोकिए",
    "bn.tap_speak_order": "बोलिए दबाकर ऑर्डर बोलिए।",
    "bn.or_upload": "या रिकॉर्डिंग डालिए",
    "bn.choose_rec": "रिकॉर्डिंग चुनिए",
    "bn.upload_bill": "डालकर बिल बनाइए",
    "bn.type_title": "लिखिए",
    "bn.what_took": "ग्राहक ने क्या लिया?",
    "bn.type_placeholder": "2 किलो टमाटर, 1 दर्जन केला",
    "bn.photo_title": "टोकरी की फोटो लीजिए",
    "bn.photo_desc": "ग्राहक की टोकरी की फोटो। गिनकर आपके दाम से बिल।",
    "bn.photo_choose_label": "टोकरी की फोटो चुनिए",
    "bn.photo_choose": "फोटो चुनिए",
    "bn.photo_btn": "फोटो डालकर बिल बनाइए",
    # --- settings ---
    "set.title": "सेटिंग — {shop}",
    "set.heading": "सेटिंग",
    "set.sub": "{shop} · आपकी दुकान, आपके हिसाब से",
    "set.profile": "दुकान ब्योरा",
    "set.name": "दुकान का नाम",
    "set.area": "इलाका",
    "set.phone": "फोन / व्हाट्सऐप",
    "set.phone_help": "7–15 अंक, + लगा सकते हैं।",
    "set.language": "भाषा",
    "set.lang_help": "किस भाषा में दाम बोलते हैं।",
    "set.currency": "मुद्रा",
    "set.type": "दुकान कैसी",
    "set.upi": "UPI ID",
    "set.upi_help": "वैकल्पिक। UPI QR के लिए चाहिए।",
    "set.payee": "UPI नाम",
    "set.payee_help": "ग्राहक के UPI में दिखेगा। नहीं तो दुकान का नाम।",
    "set.round": "बिल पूरे रुपये में करिए",
    "set.round_help": "कुल पूरे रुपये; फर्क बिल पर दिखेगा।",
    "set.save": "सहेजिए",
    "set.seller_link": "आपका विक्रेता लिंक",
    "set.seller_desc": "किसी फोन से होम, बिल, दाम खोलिए।",
    "set.keep_private": "ये लिंक छिपाकर रखिए: इससे दाम बदल सकते हैं।",
    "set.copy_prompt": "विक्रेता लिंक कॉपी करिए:",
    "dash.install_app": "ऐप इंस्टॉल करें",
    "dash.install_hint": "एक टैप में बिल बनाने के लिए MarketMate को होम स्क्रीन पर जोड़ें।",
    "dash.install_ios": "iPhone पर: Share → Add to Home Screen.",
    "dash.send_link_wa": "मेरा लिंक मेरे WhatsApp पर भेजें",
    "dash.keep_safe": "इसे संभालकर रखें",
    "bills.filter_packing": "पैकिंग",
    "bills.filter_ready": "तैयार",
    "bills.filter_collected": "ले लिया",
    "bills.pill_packing": "पैकिंग",
    "bills.pill_ready": "तैयार",
    "bills.pill_collected": "ले लिया",
    "bill.start_packing": "पैकिंग शुरू करें",
    "bill.mark_ready": "लेने के लिए तैयार",
    "bill.mark_collected": "ग्राहक ले गया",
    "bill.cancel_order": "ऑर्डर रद्द करें",
    "bill.tell_whatsapp": "ग्राहक को WhatsApp पर बताएँ",
    "bill.price_changed": "आपके ऑफ़लाइन रहने के दौरान दाम बदल गया — वसूली से पहले हर लाइन जाँच लें।",
    "bill.made_by": "{name} ने बनाया",
    "bill.order_status": "ऑर्डर की स्थिति",
    "set.add_helper": "मददगार जोड़ें",
    "set.helper_name": "मददगार का नाम",
    "set.helper_desc": "मददगार सिर्फ़ बिल बना सकते हैं। दाम, फ़ोटो, ख़रीद, सेटिंग, एक्सपोर्ट या दिन-बंद नहीं बदल सकते।",
    "set.helper_once": "यह लिंक अभी बाँट लें — यह दोबारा नहीं दिखेगा।",
    "set.helper_remove": "हटाएँ",
    "set.no_helpers": "अभी कोई मददगार नहीं।",
    "set.send_link_wa": "मेरा लिंक मेरे WhatsApp पर भेजें",
    "set.keep_safe": "इसे संभालकर रखें",
    "set.keep_safe_desc": "यह कार्ड छपवाकर दुकान में रखें। इस लिंक वाला आपकी दुकान चला सकता है।",
    "set.print_card": "सुरक्षा कार्ड छापें",
    "error.helper_title": "मददगार सिर्फ़ बिल बना सकते हैं",
    "error.helper_message": "यह पेज आपकी दुकान बदलता है, इसलिए मददगार इसे नहीं खोल सकते। दुकान मालिक से पूछें।",
    "order.step_new": "ऑर्डर मिला",
    "order.step_packing": "आपका ऑर्डर पैक हो रहा है",
    "order.step_ready": "लेने के लिए तैयार",
    "order.step_collected": "ले लिया",
    "order.step_cancelled": "रद्द",
    "order.status_label": "ऑर्डर की स्थिति",
    # --- purchases ---
    "pur.title": "खरीद — {shop}",
    "pur.heading": "आज की खरीद",
    "pur.sub": "{shop} · {today} · आज खर्च {spent}",
    "pur.say_title": "खरीद बोलिए",
    "pur.say_desc": "जैसे “प्याज़ 50 किलो 1200 रुपया”। हर संख्या सुननी चाहिए।",
    "pur.upload_label": "रिकॉर्डिंग डालिए",
    "pur.upload_check": "डालकर देखिए",
    "pur.type_title": "एक पंक्ति लिखिए",
    "pur.item": "सामान",
    "pur.qty": "मात्रा",
    "pur.unit": "इकाई",
    "pur.total_paid": "कुल दिया",
    "pur.add": "जोड़िए",
    "pur.bought_today": "आज खरीदा",
    "pur.paid_cost": "दिया {total} · लागत {cost}",
    "pur.stock_left": "बचा स्टॉक: {left}",
    "pur.empty_title": "अभी खरीदा नहीं",
    "pur.empty_text": "सुबह मंडी से क्या लाए, बोलिए या लिखिए।",
    "pur.recent": "हाल की बोली",
    "pur.purchase_n": "खरीद {id}",
    "pur.buy": "खरीद",
    "pur.sell": "बिक्री",
    # --- purchase review ---
    "pr.title": "खरीद पक्की करिए",
    "pr.heading": "खरीद पक्की करिए",
    "pr.heard": "सुना: {transcript}",
    "pr.qty_total": "{qty} {unit} · कुल {total}",
    "pr.nothing": "कुछ नहीं सुना। फिर बोलिए।",
    "pr.confirm_btn": "पक्का करिए",
    # --- day close ---
    "close.title": "दिन बंद {day} — {shop}",
    "close.heading": "दिन का हिसाब",
    "close.sub": "{shop} · {day}",
    "close.day": "दिन",
    "close.show": "दिखाइए",
    "close.sales": "बिक्री",
    "close.billed_paid": "बिल + वसूल",
    "close.bills": "बिल",
    "close.spent": "खरीद खर्च",
    "close.market_run": "मंडी",
    "close.margin": "मुनाफा",
    "close.margin_sub": "बिक्री - लागत",
    "close.cash": "नकद",
    "close.paid": "वसूल",
    "close.upi": "UPI",
    "close.card": "कार्ड",
    "close.unpaid": "बाकी",
    "close.billed_not_paid": "बिल बना, वसूल नहीं",
    "close.items_sold": "बिका",
    "close.th_item": "सामान",
    "close.th_sold": "बिका",
    "close.th_sales": "बिक्री",
    "close.th_opening": "शुरू में",
    "close.th_left": "बचा",
    "close.th_wastage": "खराब",
    "close.wastage_aria": "{display} खराब",
    "close.save_wastage": "खराब रखिए",
    "close.nothing_title": "बिल नहीं",
    "close.nothing_text": "आज के बिल यहाँ आएँगे।",
    "close.carry": "कल के लिए: बचा स्टॉक कल की शुरुआत बनेगा।",
    "close.wa_send": "व्हाट्सऐप पर भेजिए",
    "close.print_pdf": "छापिए / PDF",
    # --- board / tags PDFs ---
    "board.item": "सामान",
    "board.price": "दाम",
    "board.per": "/ {per}",
    "board.sold_out": "खत्म",
    "board.scan": "लाइव दाम के लिए स्कैन · {url}",
    "tags.today": "आज, {at}",
    # --- bill PDF ---
    "bpdf.bill": "बिल {id}",
    "bpdf.customer": "ग्राहक",
    "bpdf.item": "सामान",
    "bpdf.qty": "मात्रा",
    "bpdf.amount": "राशि",
    "bpdf.per": "/ {amount} {unit}",
    "bpdf.total": "कुल",
    "bpdf.thanks": "धन्यवाद, फिर आइए!",
    "bpdf.note": "{shop} की सूची से दाम।",
    # --- close PDF ---
    "cpdf.sales_bills": "बिक्री ({n} बिल)",
    # --- error pages ---
    "error.try_samples": "नमूना दुकान देखिए",
    "error.back_home": "होम जाइए",
    "error.too_many_title": "बहुत ज़्यादा डाला",
    "error.budget_title": "बजट खत्म",
    "error.file_big_title": "फाइल बड़ी है",
    "error.no_photo_title": "फोटो नहीं चुनी",
    "error.photo_big_title": "फोटो बड़ी है",
    "error.not_photo_title": "फोटो नहीं",
    "error.empty_rec_title": "खाली रिकॉर्डिंग",
    "error.which_item_title": "कौन सा सामान?",
    "error.unknown_action_title": "अनजान काम",
    "error.not_on_list_title": "सूची में नहीं",
    "error.count_wrong_title": "गिनती ठीक नहीं",
    "error.no_count_title": "गिनती नहीं",
    # --- WhatsApp texts ---
    "wa.bill_header": "{shop} बिल {id}",
    "wa.bill_line": "{name} {qty} {unit} - रु.{total}",
    "wa.bill_soldout": "{name} - खत्म",
    "wa.bill_not_on_list": "{name} - सूची में नहीं",
    "wa.bill_total": "कुल: रु.{total}",
    "wa.quote_header": "{shop} अनुमान",
    "wa.quote_total": "कुल: रु.{total}",
    "wa.quote_link": "अनुमान: {url}",
    "wa.summary_main": "{date}: बिक्री {sales} (नकद {cash}, UPI {upi}), {bills} बिल।",
    "wa.summary_top": "खूब बिका: {items}।",
    "wa.summary_top_item": "{label} {qty}{unit} ({amount})",
    "wa.summary_margin": "मुनाफा {margin}।",
    "wa.order_ready": "{shop} से आपका ऑर्डर लेने के लिए तैयार है। कुल रु.{total}।",
    "wa.link_self": "मेरा MarketMate विक्रेता लिंक (संभालकर रखें): {url}",
}


STRINGS: dict[str, dict[str, str]] = {
    "en": _ENGLISH,
    "ta": _TAMIL,
    "hi": _HINDI,
}

_UI_LANGS = ("en", "ta", "hi")


def _normalize_lang(lang: str | None) -> str:
    text = (lang or "").strip().lower()
    return text if text in _UI_LANGS else "en"


class StringsDict(dict):
    """Customer ``t`` dict that is also callable as ``t(key, **vars)``.

    Customer templates use ``t.key`` lookups while the shared base layout
    calls ``t('top.…')``; both work in the customer's ``?lang`` language.
    Seller pages use the Jinja global ``t`` function instead.
    """

    def __init__(self, lang: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lang = _normalize_lang(lang)

    def __call__(self, key: str, **vars: Any) -> str:
        return t_for(self._lang)(key, **vars)


def get_strings(lang: str) -> dict[str, str]:
    """Labels for a language code; anything untranslated falls back to English."""
    code = (lang or "").strip().lower()
    merged = dict(_ENGLISH)
    extra = STRINGS.get(code)
    if extra:
        merged.update(extra)
    return StringsDict(code, merged)


def lookup(key: str, lang: str) -> str:
    """Raw template for a key with English fallback, else the key itself."""
    table = STRINGS.get(_normalize_lang(lang), _ENGLISH)
    if key in table:
        return table[key]
    return _ENGLISH.get(key, key)


def t_for(lang: str):
    """Return ``t(key, **vars)`` bound to a language with English fallback."""

    code = _normalize_lang(lang)

    def t(key: str, **vars: Any) -> str:
        template = lookup(key, code)
        if "default" in vars and template == key:
            default = vars.pop("default")
            template = str(default)
        if not vars:
            return template
        try:
            return template.format(**vars)
        except (KeyError, IndexError, ValueError):
            return template

    return t


def ui_lang_from_parts(cookie_val: str | None, shop_lang: str | None) -> str:
    """Seller UI language: ``ui_lang`` cookie wins, else shop ta/hi, else en."""
    cookie = (cookie_val or "").strip().lower()
    if cookie in _UI_LANGS:
        return cookie
    shop = (shop_lang or "").strip().lower()
    if shop in ("ta", "hi"):
        return shop
    return "en"


def _shop_lang_of(shop: Any) -> str:
    if shop is None:
        return "en"
    if isinstance(shop, str):
        return shop
    try:
        return str(shop["language"] or "en")
    except (KeyError, IndexError, TypeError):
        pass
    lang = getattr(shop, "language", None)
    return str(lang or "en")


def get_ui_lang(request: Any, shop: Any = None) -> str:
    """UI language for a seller request: cookie override, else shop language."""
    cookie_val = None
    try:
        cookies = getattr(request, "cookies", None)
        if isinstance(cookies, dict):
            cookie_val = cookies.get("ui_lang")
        elif cookies is not None:
            cookie_val = cookies.get("ui_lang")  # starlette Cookies
    except (AttributeError, TypeError):
        cookie_val = None
    return ui_lang_from_parts(cookie_val, _shop_lang_of(shop))


def missing_keys() -> dict[str, list[str]]:
    """Languages mapped to sorted English keys they still lack (for tests)."""
    en_keys = set(_ENGLISH)
    return {
        lang: sorted(en_keys - set(table))
        for lang, table in STRINGS.items()
        if lang != "en"
    }


# ---------------------------------------------------------------------------
# Stages: translated stepper labels + friendly lines (stored stages stay English)
# ---------------------------------------------------------------------------

_QUOTE_KINDS = ("quote_voice", "quote_photo", "bill_voice", "bill_photo")


def _stage_group(kind: str) -> str:
    if kind == "photo":
        return "photo"
    if kind in _QUOTE_KINDS:
        return "quote"
    if kind == "live":
        return "live"
    if kind == "board":
        return "board"
    if kind == "purchase":
        return "purchase"
    return "video"


def stage_label(kind: str, key: str, lang: str = "en") -> str:
    group = _stage_group(kind)
    if group == "quote" and key == "received":
        return lookup("stage.quote.received", lang)
    template = lookup(f"stage.{group}.{key}", lang)
    if template.startswith("stage.") and group != "video":
        return lookup(f"stage.video.{key}", lang)
    return template


def stage_friendly(kind: str, key: str, lang: str = "en") -> str:
    group = _stage_group(kind)
    if group == "quote" and key == "received":
        return lookup("friendly.quote.received", lang)
    template = lookup(f"friendly.{group}.{key}", lang)
    if template.startswith("friendly.") and group != "video":
        return lookup(f"friendly.video.{key}", lang)
    return template


# ---------------------------------------------------------------------------
# Flags: key + vars at render time (stored English messages stay for data)
# ---------------------------------------------------------------------------

_SOUND_RE = re.compile(r"did you say\s+(.+?)\s+or\s+(.+?)\?", re.IGNORECASE)
_PAREN_RE = re.compile(r"\(([^)]*)\)")
_MATCHES_RE = re.compile(
    r"(.+?)\s+matches the previous price\s*\((.+?)\s+per\s+(.+?)\)",
    re.IGNORECASE,
)
_JUMP_RE = re.compile(
    r"price jumped from\s+(.+?)\s+to\s+(.+?)\s+per\s+(.+?)\s*\(last confirmed\)",
    re.IGNORECASE,
)
_PRICE_NOT_HEARD_RE = re.compile(r"price\s+(.+?)\s+not heard in quote", re.IGNORECASE)
_QTY_NOT_HEARD_RE = re.compile(r"quantity\s+(.+?)\s+not heard in quote", re.IGNORECASE)
_TOTAL_NOT_HEARD_RE = re.compile(r"total\s+(.+?)\s+not heard in quote", re.IGNORECASE)
_UNCLEAR_RE = re.compile(r'unclear number\s+"([^"]+)"\s+before currency', re.IGNORECASE)
_CORRECTION_RE = re.compile(r'seller corrected themselves\s*\(?"?([^")]*?)"?\)?\s*$', re.IGNORECASE)
_NOT_READ_RE = re.compile(r"^(.*?)\s*could not be read from your board", re.IGNORECASE)
_NEW_ITEM_RE = re.compile(r"^(.*?)\s*is not in the current price list", re.IGNORECASE)


def _sound_alike_vars(message: str, options: list[str]) -> dict[str, str]:
    a, b = "", ""
    if len(options) >= 2:
        a, b = str(options[0]), str(options[1])
    match = _SOUND_RE.search(message or "")
    if match:
        left, right = match.group(1).strip(), match.group(2).strip()
        # Plain number pairs ("18 or 80") come from options; word pairs
        # ("half a kg or 6 kg", "dozen or bunch") stay as heard.
        if a and b and left == a and right == b or a and b:
            pass
        else:
            a, b = left, right
    return {"a": a, "b": b}


def _paren_note(message: str) -> str:
    match = _PAREN_RE.search(message or "")
    return match.group(1).strip() if match else ""


def flag_text(flag: Any, lang: str = "en") -> str:
    """Translate a Flag for display; the stored ``flag.message`` stays English."""
    code = getattr(flag, "code", "") or ""
    field = getattr(flag, "field", "") or ""
    message = getattr(flag, "message", "") or ""
    options = list(getattr(flag, "options", []) or [])
    t = t_for(lang)

    if code == "SOUND_ALIKE":
        note = _paren_note(message).lower()
        tail = ""
        matches = _MATCHES_RE.search(message)
        if matches:
            tail = " " + t(
                "flag.matches_previous",
                price=matches.group(1).strip(),
                rate=matches.group(2).strip(),
                unit=matches.group(3).strip(),
            )
        if "half a" in message.lower() or "arai and aaru" in note:
            unit = ""
            for token in ("kg", "g", "piece", "dozen", "bunch", "packet", "l", "ml"):
                if token in message.lower():
                    unit = token
                    break
            return t("flag.sound_alike_half", unit=unit or "unit") + tail
        if "mandarin" in note:
            return t("flag.sound_alike_zh", x="一打", y="一扎") + tail
        if "thai" in note:
            return t("flag.sound_alike_th", x="โหล", y="โล") + tail
        pair = _sound_alike_vars(message, options)
        a, b = pair["a"], pair["b"]
        if "tamil" in note and a and b:
            xy = re.match(r"(.+?)\s+and\s+(.+?)\s+sound alike", note, re.IGNORECASE)
            x, y = (xy.group(1).strip(), xy.group(2).strip()) if xy else (a, b)
            return t("flag.sound_alike_ta", a=a, b=b, x=x, y=y) + tail
        if "hindi" in note and a and b:
            xy = re.match(r"(.+?)\s+and\s+(.+?)\s+sound alike", note, re.IGNORECASE)
            x, y = (xy.group(1).strip(), xy.group(2).strip()) if xy else (a, b)
            return t("flag.sound_alike_hi", a=a, b=b, x=x, y=y) + tail
        if "marathi" in note and a and b:
            xy = re.match(r"(.+?)\s+and\s+(.+?)\s+sound alike", note, re.IGNORECASE)
            x, y = (xy.group(1).strip(), xy.group(2).strip()) if xy else (a, b)
            return t("flag.sound_alike_mr", a=a, b=b, x=x, y=y) + tail
        if "bengali" in note and a and b:
            xy = re.match(r"(.+?)\s+and\s+(.+?)\s+sound alike", note, re.IGNORECASE)
            x, y = (xy.group(1).strip(), xy.group(2).strip()) if xy else (a, b)
            return t("flag.sound_alike_bn", a=a, b=b, x=x, y=y) + tail
        if a and b:
            return t("flag.sound_alike", a=a, b=b) + tail
        return message
    if code == "NOT_HEARD":
        match = _PRICE_NOT_HEARD_RE.search(message)
        if match:
            return t("flag.not_heard_price", price=match.group(1).strip())
        match = _QTY_NOT_HEARD_RE.search(message)
        if match:
            return t("flag.not_heard_qty", qty=match.group(1).strip())
        match = _TOTAL_NOT_HEARD_RE.search(message)
        if match:
            return t("flag.not_heard_total", total=match.group(1).strip())
        if field == "total_cost":
            return t("flag.number_check")
        return message
    if code == "NUMBER_CHECK":
        return t("flag.number_check")
    if code == "UNIT_MISSING":
        if field == "unit" and "quantity" in message.lower():
            return t("flag.unit_missing_qty")
        return t("flag.unit_missing")
    if code == "UNIT_ODD":
        return t("flag.unit_odd")
    if code == "UNIT_CHECK":
        return t("flag.unit_check")
    if code == "UNIT_FROM_EARLIER":
        return t("flag.unit_from_earlier")
    if code == "JUMP":
        match = _JUMP_RE.search(message)
        if match:
            return t(
                "flag.jump",
                old=match.group(1).strip(),
                current=match.group(2).strip(),
                unit=match.group(3).strip(),
            )
        return message
    if code == "RANGE":
        return t("flag.range")
    if code == "TWO_PRICES":
        return t("flag.two_prices")
    if code == "NO_PRICE":
        if field == "total_cost" or "total" in message.lower():
            return t("flag.no_total")
        return t("flag.no_price")
    if code == "QTY_MISSING":
        if "heard" in message.lower():
            return t("flag.qty_missing_heard")
        return t("flag.qty_missing")
    if code == "CORRECTION_SAID":
        match = _CORRECTION_RE.search(message)
        marker = match.group(1).strip().strip("\"'") if match else ""
        if marker:
            return t("flag.correction", marker=marker)
        return t("flag.correction", marker="")
    if code == "UNCLEAR_NUMBER":
        match = _UNCLEAR_RE.search(message)
        if match:
            return t("flag.unclear_number", before=match.group(1))
        return message
    if code == "BOARD_CONFIRM":
        return t("flag.board_confirm")
    if code == "NOT_READ":
        match = _NOT_READ_RE.search(message)
        name = match.group(1).strip() if match else ""
        return t("flag.not_read", name=name or "this line")
    if code == "NEW_ITEM":
        match = _NEW_ITEM_RE.search(message)
        name = match.group(1).strip() if match else ""
        return t("flag.new_item", name=name or message)
    return message


# ---------------------------------------------------------------------------
# Photos: translated count wording + suggestions (stored report stays English)
# ---------------------------------------------------------------------------

def photo_quality_text(quality: str, lang: str = "en") -> str:
    t = t_for(lang)
    key = {
        "dark": "phr.quality_dark",
        "blurry": "phr.quality_blurry",
        "too far": "phr.quality_far",
    }.get((quality or "").strip().lower())
    if key is None:
        return quality
    return t(key)


def photo_count_text(product: dict, lang: str = "en") -> str:
    t = t_for(lang)
    if not product.get("countable"):
        return ""
    span = product.get("count_range")
    count = product.get("count")
    if product.get("needs_check") and span and len(span) == 2:
        return t("phr.count_range", a=span[0], b=span[1])
    if product.get("needs_check") and isinstance(count, int):
        return t("phr.count_about_check", n=count)
    if isinstance(count, int):
        return t("phr.count_about", n=count)
    return ""


def photo_suggestion_text(suggestion: dict, products: list[dict],
                          lang: str = "en") -> str:
    t = t_for(lang)
    kind = suggestion.get("kind") or ""
    raw_name = str(suggestion.get("item_name") or "").strip()
    name = raw_name[:1].upper() + raw_name[1:] if raw_name else raw_name
    if kind == "retake":
        quality = str(suggestion.get("value") or "").strip().lower()
        if quality not in ("dark", "blurry", "too far"):
            # Stored retake text embeds the quality word in English.
            stored = str(suggestion.get("text") or "").lower()
            for candidate in ("dark", "blurry", "too far"):
                if candidate in stored:
                    quality = candidate
                    break
        return t("phr.sugg_retake",
                 quality=photo_quality_text(quality or "dark", lang))
    if kind == "add_price":
        return t("phr.sugg_add_price", name=name)
    if kind == "back_on_sale":
        return t("phr.sugg_back", name=name)
    if kind == "check_count":
        low = high = None
        value = suggestion.get("value")
        if isinstance(value, (list, tuple)) and len(value) == 2:
            low, high = value
        else:
            for product in products:
                if (product.get("name_en") or "").strip().lower() == raw_name.lower():
                    span = product.get("count_range") or []
                    if len(span) == 2:
                        low, high = span
                    break
        if low is not None and high is not None:
            return t("phr.sugg_check_count", name=name, low=low, high=high)
        return str(suggestion.get("text") or "")
    if kind == "set_stock":
        count = suggestion.get("value")
        if not isinstance(count, int):
            for product in products:
                if (product.get("name_en") or "").strip().lower() == raw_name.lower():
                    if isinstance(product.get("count"), int):
                        count = product.get("count")
                    break
        if isinstance(count, int):
            return t("phr.sugg_set_stock", count=count, name=raw_name or name)
        return str(suggestion.get("text") or "")
    return str(suggestion.get("text") or "")


def photo_button_text(action: str | None, lang: str = "en") -> str:
    t = t_for(lang)
    return {
        "set_stock": t("phr.btn_save_stock"),
        "unsold": t("phr.btn_back_sale"),
        "voice_update": t("phr.btn_say_price"),
    }.get(action or "", t("phr.btn_retake"))


# ---------------------------------------------------------------------------
# WhatsApp texts from seller pages (bill, quote, day summary)
# ---------------------------------------------------------------------------

def _display(name: str) -> str:
    return name[:1].upper() + name[1:] if name else name


def _fmt_number(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        from decimal import Decimal

        return format(Decimal(str(value)).normalize(), "f")
    except (ArithmeticError, ValueError, AttributeError):
        return str(value)


def bill_whatsapp_text(shop: Any, bill_id: int, raw_lines: list[dict],
                       total: Any, lang: str = "en") -> str:
    t = t_for(lang)
    try:
        shop_name = shop["name"]
    except (KeyError, IndexError, TypeError):
        shop_name = getattr(shop, "name", "shop")
    parts = [t("wa.bill_header", id=bill_id, shop=shop_name)]
    for raw in raw_lines or []:
        if not isinstance(raw, dict):
            continue
        name = _display(str(raw.get("name_en") or ""))
        status = raw.get("status", "")
        if status in ("priced", "needs_qty") and raw.get("line_total"):
            parts.append(t(
                "wa.bill_line", name=name,
                qty=_fmt_number(raw.get("qty", "")),
                unit=raw.get("unit") or "",
                total=_fmt_number(raw["line_total"])).strip())
        elif status == "sold_out":
            parts.append(t("wa.bill_soldout", name=name))
        else:
            parts.append(t("wa.bill_not_on_list", name=name))
    parts.append(t("wa.bill_total", total=_fmt_number(total)))
    return "\n".join(parts)


def quote_whatsapp_text(shop: Any, raw_lines: list[dict], total: Any,
                        quote_url: str, lang: str = "en") -> str:
    t = t_for(lang)
    try:
        shop_name = shop["name"]
    except (KeyError, IndexError, TypeError):
        shop_name = getattr(shop, "name", "shop")
    parts = [t("wa.quote_header", shop=shop_name)]
    for raw in raw_lines or []:
        if not isinstance(raw, dict):
            continue
        name = _display(str(raw.get("name_en") or ""))
        status = raw.get("status", "")
        if status in ("priced", "needs_qty") and raw.get("line_total"):
            parts.append(t(
                "wa.bill_line", name=name,
                qty=_fmt_number(raw.get("qty", "")),
                unit=raw.get("unit") or "",
                total=_fmt_number(raw["line_total"])).strip())
        elif status == "sold_out":
            parts.append(t("wa.bill_soldout", name=name))
        else:
            parts.append(t("wa.bill_not_on_list", name=name))
    parts.append(t("wa.quote_total", total=_fmt_number(total)))
    parts.append(t("wa.quote_link", url=quote_url))
    return "\n".join(parts)


def summary_whatsapp_text(day: str, tiles: dict, items: list[dict],
                          lang: str = "en") -> str:
    from decimal import Decimal, InvalidOperation

    from app.outputs.money import format_money

    t = t_for(lang)
    try:
        from datetime import datetime as _dt

        short = _dt.strptime(day, "%Y-%m-%d").strftime("%d %b")
    except ValueError:
        short = day
    # Amounts are preformatted by the caller (dayclose keeps money via filter).
    sales = tiles.get("sales_fmt", tiles.get("sales", 0))
    cash = tiles.get("cash_fmt", tiles.get("cash", 0))
    upi = tiles.get("upi_fmt", tiles.get("upi", 0))
    bills = tiles.get("bills_count", 0)
    top = sorted(items, key=lambda r: r.get("sales_amount", Decimal(0)),
                 reverse=True)[:3]
    parts = []
    for entry in top:
        qty = entry.get("sold_qty")
        unit = entry.get("unit") or ""
        amount = entry.get("sales_amount_fmt", entry.get("sales_amount", 0))
        if qty is None:
            qty_text = ""
        else:
            try:
                qty_text = format(Decimal(qty).normalize(), "f")
            except (InvalidOperation, ValueError, AttributeError):
                qty_text = str(qty)
        label = entry.get("display") or entry.get("name_en", "")
        parts.append(t("wa.summary_top_item", label=label, qty=qty_text,
                       unit=unit, amount=amount).strip())
    text = t("wa.summary_main", date=short, sales=sales, cash=cash, upi=upi,
             bills=bills)
    if parts:
        text += " " + t("wa.summary_top", items=", ".join(parts))
    margin = tiles.get("margin")
    if margin is not None:
        margin_fmt = tiles.get("margin_fmt", margin)
        if not isinstance(margin_fmt, str):
            margin_fmt = format_money(margin, tiles.get("currency", "INR"))
        text += " " + t("wa.summary_margin", margin=margin_fmt)
    return text


def _shop_lang(shop: Any) -> str:
    try:
        code = (shop["language"] or "en").strip().lower()
    except (KeyError, IndexError, TypeError):
        code = "en"
    return code if code in ("ta", "hi") else "en"


def order_ready_whatsapp_text(shop: Any, total: Any) -> str:
    """Short 'ready for pickup' message in the shop's language."""
    t = t_for(_shop_lang(shop))
    try:
        shop_name = shop["name"]
    except (KeyError, IndexError, TypeError):
        shop_name = getattr(shop, "name", "shop")
    return t("wa.order_ready", shop=shop_name,
             total=_fmt_number(total))


def link_self_whatsapp_url(shop: Any, seller_url: str) -> str:
    """wa.me link to the shop's own phone carrying the seller link."""
    import re
    from urllib.parse import quote as _quote

    try:
        phone = shop["phone"] or ""
    except (KeyError, IndexError, TypeError):
        phone = ""
    digits = re.sub(r"\D", "", phone)
    t = t_for(_shop_lang(shop))
    text = t("wa.link_self", url=seller_url)
    return f"https://wa.me/{digits}?text={_quote(text)}"


# ---------------------------------------------------------------------------
# Jinja globals: t(key, **vars) + t_flag(flag) via the request's UI language
# ---------------------------------------------------------------------------

def _context_lang(ctx: Any) -> str:
    try:
        explicit = ctx.get("ui_lang")  # type: ignore[union-attr]
    except (AttributeError, TypeError):
        explicit = None
    if isinstance(explicit, str) and explicit.strip().lower() in _UI_LANGS:
        return explicit.strip().lower()
    request = None
    shop = None
    shop_lang = None
    try:
        request = ctx.get("request")  # type: ignore[union-attr]
    except (AttributeError, TypeError):
        request = None
    try:
        shop = ctx.get("shop")  # type: ignore[union-attr]
    except (AttributeError, TypeError):
        shop = None
    try:
        shop_lang = ctx.get("shop_lang")  # type: ignore[union-attr]
    except (AttributeError, TypeError):
        shop_lang = None
    if shop is None and isinstance(shop_lang, str):
        shop = {"language": shop_lang}
    return get_ui_lang(request, shop)


def jinja_t(ctx: Any, key: str, **vars: Any) -> str:
    """Jinja global ``t``: translate ``key`` in the request's UI language."""
    return t_for(_context_lang(ctx))(key, **vars)


def jinja_flag(ctx: Any, flag: Any) -> str:
    """Jinja global ``t_flag``: translated flag message at render time."""
    try:
        return flag_text(flag, _context_lang(ctx))
    except (AttributeError, TypeError, ValueError):
        return getattr(flag, "message", "") or ""


try:  # Jinja pass_context when available; plain call otherwise.
    from jinja2 import pass_context as _pass_context

    jinja_t = _pass_context(jinja_t)  # type: ignore[assignment]
    jinja_flag = _pass_context(jinja_flag)  # type: ignore[assignment]
except ImportError:  # pragma: no cover - jinja2 is a hard dependency
    pass

