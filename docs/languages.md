# Languages

MarketMate accepts all 25 Muse Voice languages. The shop form lists
every language by native name, and Voice Transcribe is called with
`languageBias` set to the shop language plus English.

## Synthetic benchmark

These results come from synthetic test clips, not real market
recordings: each clip pairs a macOS voice speaking 4 items with
Wikimedia photos of those items. Every language uses the same
4 items (tomato, onion, banana, coconut) with local-currency test
prices; see `eval/lang/scripts.json`.
There was one run per language, and results vary run to run.
"wrong-unflagged" means a wrong price or unit shown with no warning;
"flagged only" means every miss was flagged (honest, but the seller
must tap to fix it).

Provider for text steps: `meta` (image steps always use Meta).

| native name | English name | voice | found/4 | exact/4 | flagged | wrong-unflagged | cost | seconds | notes |
|---|---|---|---|---|---|---|---|---|---|
| العربية | Arabic | Majed | 4/4 | 4/4 | 0 | 0 | $0.0497 | 56.8 | ok |
| বাংলা | Bengali | Piya | 4/4 | 3/4 | 1 | 0 | $0.0530 | 47.0 | flagged only |
| Deutsch | German | Anna | 4/4 | 4/4 | 0 | 0 | $0.0504 | 56.7 | ok |
| English | English | Aman (English (India)) | 4/4 | 4/4 | 0 | 0 | $0.0472 | 36.4 | ok |
| Español | Spanish | Eddy (Spanish (Spain)) | 4/4 | 4/4 | 0 | 0 | $0.0514 | 54.1 | ok |
| Français | French | Eddy (French (France)) | 4/4 | 4/4 | 0 | 0 | $0.0509 | 38.7 | ok |
| עברית | Hebrew | Carmit | 4/4 | 4/4 | 0 | 0 | $0.0529 | 54.5 | ok |
| हिन्दी | Hindi | Lekha | 4/4 | 3/4 | 1 | 0 | $0.0540 | 38.4 | flagged only |
| Bahasa Indonesia | Indonesian | Damayanti | 4/4 | 4/4 | 0 | 0 | $0.0528 | 48.6 | ok |
| Italiano | Italian | Alice | 4/4 | 4/4 | 0 | 0 | $0.0545 | 61.5 | ok |
| 日本語 | Japanese | Eddy (Japanese (Japan)) | 4/4 | 4/4 | 0 | 0 | $0.0515 | 40.3 | ok |
| ಕನ್ನಡ | Kannada | Soumya | 4/4 | 4/4 | 0 | 0 | $0.0505 | 42.1 | ok |
| 한국어 | Korean | Eddy (Korean (South Korea)) | 4/4 | 4/4 | 0 | 0 | $0.0500 | 42.6 | ok |
| मराठी | Marathi | - | 0/4 | 0/4 | 0 | 0 | $0.0000 | 0.0 | not tested (no test voice) |
| Bahasa Melayu | Malay | Amira | 4/4 | 4/4 | 0 | 0 | $0.0515 | 63.9 | ok |
| Nederlands | Dutch | Xander | 4/4 | 4/4 | 0 | 0 | $0.0514 | 59.4 | ok |
| Polski | Polish | Zosia | 4/4 | 4/4 | 0 | 0 | $0.0484 | 40.2 | ok |
| Português | Portuguese | Eddy (Portuguese (Brazil)) | 4/4 | 3/4 | 1 | 0 | $0.0580 | 47.8 | flagged only |
| தமிழ் | Tamil | Vani | 4/4 | 4/4 | 0 | 0 | $0.0555 | 44.9 | ok |
| తెలుగు | Telugu | Geeta | 3/4 | 3/4 | 0 | 0 | $0.0501 | 44.2 | needs work |
| ไทย | Thai | Kanya | 4/4 | 4/4 | 0 | 0 | $0.0503 | 41.4 | ok |
| Tagalog | Tagalog | - | 0/4 | 0/4 | 0 | 0 | $0.0000 | 0.0 | not tested (no test voice) |
| Türkçe | Turkish | Yelda | 4/4 | 4/4 | 0 | 0 | $0.0494 | 51.3 | ok |
| Tiếng Việt | Vietnamese | Linh | 4/4 | 4/4 | 0 | 0 | $0.0483 | 41.0 | ok |
| 中文 | Mandarin Chinese | Eddy (Chinese (China mainland)) | 3/4 | 2/4 | 1 | 0 | $0.0534 | 46.3 | needs work |

Summary: tested 23 of 25 languages; 18 reached 4/4 exact with no wrong-unflagged; 3 flagged only; 2 need work; 2 not tested (no test voice or no clip).

## What went wrong

- Bengali - banana: heard 7 instead of 60 (flagged: did you say 7 or 60? (shaat and saat sound alike in Bengali))
- Hindi - banana: no price heard (wanted 60) (flagged: unclear number "साथ" before currency)
- Portuguese - tomato: no price heard (wanted 9) (flagged: no price at all)
- Telugu - coconut: not in the transcript (speech step lost the sentence)
- Mandarin Chinese - tomato: no price heard (wanted 8) (flagged: no price at all)
- Mandarin Chinese - coconut: not in the transcript (speech step lost the sentence)
