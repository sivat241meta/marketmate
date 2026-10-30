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

# Sample shop photo credits (Task 116)

The five sample shops ship with Unsplash photos so the site is
not empty: one stall/market cover per shop in
`app/web/static/sample/covers/` (1600px + 800px progressive
JPEG, EXIF stripped, each under 300 KB) and one product photo
per price-list item in `app/web/static/sample/items/` (WebP,
each under 120 KB). Item photos went through the same photo
step the app uses (SAM 3.1 cut-out + the Spark photo check);
15 of the 53 kept the original photo cropped square when no
cut-out verified. No photo shows a watermark, a brand logo, or
an identifiable face as its main subject.

Licence for every photo below: **Unsplash License**
(https://unsplash.com/license).

## Covers

| File | Unsplash image | Photographer | Page | SHA-256 |
|---|---|---|---|---|
| covers/selvi-vegetable-stall.jpg | photo-1761567523932-6c461c249729 | Urja Bhatt 🕊️ | https://unsplash.com/photos/assortment-of-fresh-vegetables-and-fruits-at-a-market-i8WCZpehUIs | 356c0eabfddb8b31241bef246101ccfbcc768e9b9784e4d720292f856ddc3cd1 |
| covers/selvi-vegetable-stall-800.jpg | photo-1761567523932-6c461c249729 | Urja Bhatt 🕊️ | https://unsplash.com/photos/assortment-of-fresh-vegetables-and-fruits-at-a-market-i8WCZpehUIs | 8c91d38ebfcc597078930465b814cbbf7cca57b26044ac2c57182f31c5c9486d |
| covers/pandian-fruit-centre.jpg | photo-1488459716781-31db52582fe9 | Jacopo Maiarelli | https://unsplash.com/photos/assorted-fruits-at-the-market--gOUx23DNks | dbf1a2dbf66eea90d85d5f77cd70f54c08994722ae78d0dc63fbc431849b9085 |
| covers/pandian-fruit-centre-800.jpg | photo-1488459716781-31db52582fe9 | Jacopo Maiarelli | https://unsplash.com/photos/assorted-fruits-at-the-market--gOUx23DNks | e2b6c31fd018abf66d456a087df26616ce4a2076c7c52a110a0b616d1f5f55d9 |
| covers/amma-keerai-kadai.jpg | photo-1768734837711-1fcab086d826 | Tofan Teodor | https://unsplash.com/photos/pile-of-fresh-green-beans-on-a-market-stall-ofYQCDKdh3Y | c3734bee91e3db5ed3fe6c8a400ea3d9bcf9be50521e62c2037532932e5b24cf |
| covers/amma-keerai-kadai-800.jpg | photo-1768734837711-1fcab086d826 | Tofan Teodor | https://unsplash.com/photos/pile-of-fresh-green-beans-on-a-market-stall-ofYQCDKdh3Y | 116e41afa5e1f02920c23a5f63a31c7bdf1d7f5d5ed130d00e84821610700b9c |
| covers/gupta-sabzi-wale.jpg | photo-1759003103614-11427d946af0 | Sateesh Reddy Patlolla | https://unsplash.com/photos/fresh-vegetables-displayed-at-an-outdoor-market-Sya_pQnqx8Y | 705efb3b03056abe2e5ffc90f4fad2ed688622149d7c9ed0e1300de31c9aa17f |
| covers/gupta-sabzi-wale-800.jpg | photo-1759003103614-11427d946af0 | Sateesh Reddy Patlolla | https://unsplash.com/photos/fresh-vegetables-displayed-at-an-outdoor-market-Sya_pQnqx8Y | c1893f29b1e4c55a5916c6cecf199de7cf1905caa84ae64656d6987ee08199d3 |
| covers/green-basket.jpg | photo-1609780447631-05b93e5a88ea | Alexander Schimmeck | https://unsplash.com/photos/market-stall-with-fresh-tropical-fruit-2zJhA9RSkys | a066a847b2827b5a3169ad2538f5fa6e14666d95c701437de04ea30ca17c7b0f |
| covers/green-basket-800.jpg | photo-1609780447631-05b93e5a88ea | Alexander Schimmeck | https://unsplash.com/photos/market-stall-with-fresh-tropical-fruit-2zJhA9RSkys | 42352d24d0aab1fdbbff6e2f32f34592d6562dbc48494169dfbc1f9ded358198 |

## Items

| File | Unsplash image | Photographer | Page | SHA-256 |
|---|---|---|---|---|
| items/selvi-vegetable-stall__tomato.webp | photo-1582284540020-8acbe03f4924 | engin akyurt | https://unsplash.com/photos/red-tomatoes-on-brown-wooden-table-eb26eV-ys_k | 5e1370621a5d6d58e9023388e75fbaac82d1b8bdfbfa5046565d7c00e1f9814f |
| items/selvi-vegetable-stall__onion.webp | photo-1760368104753-fe0994f94ff3 | Ignat Kushnarev | https://unsplash.com/photos/a-pile-of-fresh-red-onions-with-roots-GHOrJvaTicI | abb9441c80fc4bf1bf9795053ef79d2125189ca5abb4fa2694f3f16a8c67d2f0 |
| items/selvi-vegetable-stall__small-onion.webp | photo-1759421278110-ab77256dc555 | feey | https://unsplash.com/photos/a-pile-of-shallots-on-a-textured-surface-EiThi2XdgsA | e6752c1023d38302b960497690a29788996b32981b7bc4d26559546853a18636 |
| items/selvi-vegetable-stall__potato.webp | photo-1518977676601-b53f82aba655 | Lars Blankers | https://unsplash.com/photos/brown-potato-lot-B0s3Xndk6tw | 7fcbae2d93caa398d67160a89dfc7959e5749fcbf75973688ca9e748dbec63e9 |
| items/selvi-vegetable-stall__carrot.webp | photo-1598170845058-32b9d6a5da37 | K8 | https://unsplash.com/photos/carrots-with-green-leafy-tops-GHRT9j21m2M | 0ed4938612c3a13c689379c57062a1f783204e09e94a1fcab77bcdad6c3ba713 |
| items/selvi-vegetable-stall__beans.webp | photo-1574963835594-61eede2070dc | Bob Bowie | https://unsplash.com/photos/green-kentucky-beans-2JDWDtCGREA | 34374dc097730542d4b67c2d7a5812197fc82fb628959c4f6087c719e9e97073 |
| items/selvi-vegetable-stall__brinjal.webp | photo-1683543122945-513029986574 | engin akyurt | https://unsplash.com/photos/a-pile-of-purple-eggplant-with-green-stems-d6I1ZNZJcNo | 7a5b4c15fc7f03e70810b2f64f7e053411edd4ce16094d883dd1de80c4fc4c84 |
| items/selvi-vegetable-stall__ladies-finger.webp | photo-1425543103986-22abb7d7e8d2 | Neha Deshmukh | https://unsplash.com/photos/okra-vegetable-in-white-bowl-CoIJlCZEjnw | 6c01a6e2bf2191ba61630a574664bc9bf4a42645fe0116058934bea5eec0fbf5 |
| items/selvi-vegetable-stall__drumstick.webp | photo-1789921528172-65452da09883 | Nandha Kumar | https://unsplash.com/photos/drumstick-pods-in-white-sack-gV8v9NcxwDY | 0b6c7cc86682e161bbe0c092908fddc6b887279bf912cdc416e6bd219544c72a |
| items/selvi-vegetable-stall__cabbage.webp | photo-1611105637889-3afd7295bdbf | ibuki Tsubo | https://unsplash.com/photos/green-leaf-vegetable-on-white-surface-7iRMOXXxH7c | 3f865070d78bb24dc15a1d2fb5e51920369bc907304843a081385065a2629705 |
| items/selvi-vegetable-stall__cauliflower.webp | photo-1566842600175-97dca489844f | Irene Kredenets | https://unsplash.com/photos/cauliflower-lot-zNsSGYXaeP8 | 9e9d82159784a23b3d883d7a681b99ba6d5957264d5c0123e226f65abf443aa6 |
| items/selvi-vegetable-stall__green-chilli.webp | photo-1599987141071-f5810d32e21a | Hari Krishnan | https://unsplash.com/photos/green-chili-on-white-surface-f1BMuugVyyM | 2b2fc97a0a3f590e167139dbf4be746c73153805077de81555634dee76bf1131 |
| items/pandian-fruit-centre__banana--poovan.webp | photo-1571771894821-ce9b6c11b08e | Giorgio Trovato | https://unsplash.com/photos/yellow-bananas-fczCr7MdE7U | 5d70fb6007f79c559073bce225f02b2abfd31e8200fdd0e49d0d7cd272737932 |
| items/pandian-fruit-centre__banana--nendran.webp | photo-1603833665858-e61d17a86224 | Rodrigo dos Reis | https://unsplash.com/photos/ripe-yellow-bananas-in-clusters-DkTuGvgPotA | af08480a3861af8e44a18e15d0232f259104111dc8a94df2448da1d2fece7cec |
| items/pandian-fruit-centre__banana--rasthali.webp | photo-1640958900081-7b069dd23e9c | Gabriel Mihalcea | https://unsplash.com/photos/a-bunch-of-bananas-sitting-on-top-of-a-white-table-1jyRHJPkpz8 | 9d2b64f2d95a9c3c202e46474d7b355decca06d05919d3d30ddc48879dd2fcf6 |
| items/pandian-fruit-centre__papaya.webp | photo-1763502872003-f340e2474e88 | laura acevedo | https://unsplash.com/photos/pile-of-ripe-papayas-at-a-market-eOSPFa_1toU | c3d5131c92251ec4e3106cf7bbaaf4e1742b6fdbc13ecf5906136f949cd74cc7 |
| items/pandian-fruit-centre__guava.webp | photo-1689996647099-a7a0b67fd2f6 | SAMIUL ITM | https://unsplash.com/photos/a-pile-of-green-fruit-sitting-on-top-of-a-wooden-table-c-RJoTVGlc4 | 1741b17d9426f0b0b5323784798e1cd7c881c645f4c5b064931886a952c98614 |
| items/pandian-fruit-centre__pomegranate.webp | photo-1574709755254-fcd942d09d5a | Margarita Zueva | https://unsplash.com/photos/red-pomegranate-Ws4axEMbsvY | 4aa0ba01f082ca4475da2927201829f3cdc36adb61949ff50c30af373563073b |
| items/pandian-fruit-centre__grapes.webp | photo-1698305819486-ecca56daaba3 | Kiran CK | https://unsplash.com/photos/a-bunch-of-grapes-sitting-on-top-of-a-table-RdI-YMBLhNY | 01bf32097c938c7055167d3ed43b5eb9292e045580449bda95188b4ba9187806 |
| items/pandian-fruit-centre__orange.webp | photo-1611080626919-7cf5a9dbab5b | Jen Gunter | https://unsplash.com/photos/oranges-in-a-large-pile-A4BBdJQu2co | dc70febef6f1a8d090f010ed5378a3b03e052dc3cfaab5a6e325706fec73f842 |
| items/pandian-fruit-centre__apple.webp | photo-1560806887-1e4cd0b6cbd6 | Matheus Cenali | https://unsplash.com/photos/bunch-of-red-apples-wXuzS9xR49M | a2f0bc757245b21d181d04fa266668d65a344e59295854b0836a712d60669e9b |
| items/pandian-fruit-centre__pineapple.webp | photo-1550258987-190a2d41a8ba | Fernando Andrade | https://unsplash.com/photos/ripe-pineapple-fruit-nAOZCYcLND8 | 6d11b3050b95dc612577b93a350f07b56d7d1c73fb7ae1a9ebe79b17952bb771 |
| items/amma-keerai-kadai__spinach.webp | photo-1574316071802-0d684efa7bf5 | Shutter Sphere Collective | https://unsplash.com/photos/fresh-green-spinach-leaves-6AAptb2kBak | fe4b799c41484d4b4828956faeeeec5c3713b540338351c83ca9ff02225452bc |
| items/amma-keerai-kadai__amaranth.webp | photo-1617884638394-d9eef1b0f40e | Monika Grabkowska | https://unsplash.com/photos/green-and-purple-leaves-with-water-droplets-i14VzlCp-Eo | af25993b5f4039dcc7042f49b145922afc40b6ab7f099417cf836f281c57999f |
| items/amma-keerai-kadai__amaranth-2.webp | photo-1664883885923-788ba85e3110 | Ram Kishor | https://unsplash.com/photos/a-group-of-leaves-RTr1EyuZtDQ | d334801e60d6d6a24cfdd0d50f5db3d8cfa02edaa3c643da933575be9c430ab4 |
| items/amma-keerai-kadai__fenugreek-leaves.webp | photo-1654151749030-9e931772e555 | C P | https://unsplash.com/photos/a-close-up-of-a-bunch-of-green-plants-Yz9s7tg9Yr0 | bf2456c4185d963295b23103e091509c1ae931e413da1e85eec059dfb4b8b686 |
| items/amma-keerai-kadai__coriander.webp | photo-1776089770931-e422e57f760c | Natalie Kinnear | https://unsplash.com/photos/fresh-cilantro-leaves-with-a-soft-green-background-hx_vvcIiRzw | 280c22bbfd7200ccbb4682fd1f1934a9dbd69135babc919c015d21921746082e |
| items/amma-keerai-kadai__mint.webp | photo-1618130070080-91f4d55a2383 | SIMON LEE | https://unsplash.com/photos/green-mint-leaves-texture-bHWRSq8fUUE | 0d2bdc101fb75274ebd16928dd7b65d2a8deaafb037ccc5ed7ad11c19bf1e355 |
| items/amma-keerai-kadai__spring-onion.webp | photo-1559836833-2a2c99b1f54f | Laura Mitulla | https://unsplash.com/photos/green-spring-onions-CQOm4U4E71M | c01e02ecbc3f6f26a6ae20745d967bc432bf5c7d5a3048fb2af668b8cedc93ec |
| items/amma-keerai-kadai__moringa-leaves.webp | photo-1771643033515-0028fd03b708 | David Clode | https://unsplash.com/photos/close-up-of-vibrant-green-moringa-leaves-on-branches-fz7nSSfQDZo | b6dfcdd9209135c1f77c0dd531244bb28a21f0744047deee10f90cfba949479f |
| items/amma-keerai-kadai__coconut.webp | photo-1777732786332-3e78390f76aa | Saravanan Narayanan | https://unsplash.com/photos/a-pile-of-brown-coconuts-with-husks-ha4CPWwTXMs | 6f7df77c676e67deb4c6acf567dd27202639a6734228e1705ec0f2500958a23d |
| items/amma-keerai-kadai__banana-leaf.webp | photo-1528207620916-db0d5aab17cb | Eline Somers | https://unsplash.com/photos/a-close-up-of-a-large-green-leaf-cyqtI1LcMWY | d5fa5a7cd06527012571d9301b70ba2fc79b814b744bae47832080349692d904 |
| items/amma-keerai-kadai__curry-leaves.webp | photo-1789194980416-35d3d64cc805 | Sujana Rahman | https://unsplash.com/photos/hand-holding-fresh-green-curry-leaves-Dx8wkE6GgxY | 4a50cc3400c839e16d68ad829ad0877d602603c4f3c1c823f31578c280dd2ea6 |
| items/gupta-sabzi-wale__tomato.webp | photo-1769489023745-5d4effc83b9e | Jason Leung | https://unsplash.com/photos/a-large-pile-of-ripe-red-tomatoes-on-vines-J1HgNWUPzXo | 63c871973a8565c67448117042223b1e2a1d92701b18fc65f77f00eb2bbac6d4 |
| items/gupta-sabzi-wale__onion.webp | photo-1774978612854-de6a81b2cb39 | Adhitya Sibikumar | https://unsplash.com/photos/pile-of-red-onions-at-a-market-yAVMlADwbnU | e327bb55b9379e0e62f7c963ee7083f1f7535a8da233a4f5a2aaebcea113d275 |
| items/gupta-sabzi-wale__potato.webp | photo-1590165482129-1b8b27698780 | Rodrigo dos Reis | https://unsplash.com/photos/pile-of-raw-yellow-potatoes-h3AkzboxK4Q | 8b8958bb5c124181272b68e746292c96325c6a7cba9d0f99a631dbe18c846316 |
| items/gupta-sabzi-wale__cauliflower.webp | photo-1784043437088-c86a43eb695d | engin akyurt | https://unsplash.com/photos/fresh-cauliflower-heads-displayed-at-market-cjxRVLDLG8w | a592d05662eee81ddba016137f765c996868754c5719740d112d3c8dde0f6767 |
| items/gupta-sabzi-wale__cabbage.webp | photo-1781344107811-8431aba9942b | Prabhath Ilangakoon | https://unsplash.com/photos/a-pile-of-fresh-green-savoy-cabbages-with-textured-leaves-crAXyYC4bjk | c5c6eb3a05032a045a9126bd60c9d982c896f512f8add9c35c8435dd272f7bed |
| items/gupta-sabzi-wale__peas.webp | photo-1690023614293-ac2ba2eb0731 | Anita Austvika | https://unsplash.com/photos/a-pile-of-peas-and-peas-on-a-table-T9FZiRp0XKw | 17d98a34067ad80114592f0f550da44469d6e3f6162979a3ed5c6a7165230a8c |
| items/gupta-sabzi-wale__radish.webp | photo-1762710526515-b5c1f45d69ef | liam matthews | https://unsplash.com/photos/white-radishes-and-bitter-melons-in-a-crate-0BCwHPrs9hM | 249e40752fdfab6cb14d73fc4d77c75555b24daed65a23d971e7eb70a233e70d |
| items/gupta-sabzi-wale__spinach.webp | photo-1784043436675-dbe53cbcec88 | engin akyurt | https://unsplash.com/photos/fresh-green-spinach-leaves-with-pink-stems-NoxzzaDGkfs | 2e977447425df96906aab0f8b7b86810676a0cf3c11e2404697aab26a7f53265 |
| items/gupta-sabzi-wale__ladies-finger.webp | photo-1558408525-1092038389ae | Elianna Friedman | https://unsplash.com/photos/ladies-finger-lo-uDeMugA9ojU | 784a6e2f99852c7976d9f2f6ef7478881906e7e92b74e598dbd5af2c3f9b161c |
| items/gupta-sabzi-wale__brinjal.webp | photo-1528826007177-f38517ce9a8a | charlesdeluvio | https://unsplash.com/photos/purple-eggplant-sRBUzcxqt6c | 788bb66d165a6d8584386246ac89d2075744eb357252d663ed675e6e1ed3ad73 |
| items/green-basket__tomato.webp | photo-1518977822534-7049a61ee0c2 | Lars Blankers | https://unsplash.com/photos/top-view-of-tomatoes-6Z7Ss9jlEL0 | da23c0a69e463033520d7b0de0f2667d3323863429ddad729201628c63b1eda0 |
| items/green-basket__onion.webp | photo-1605197378298-02bf0af1c896 | Paul Magdas | https://unsplash.com/photos/red-onion-on-brown-wooden-crate-SSIwIRCu7bM | d77011123b03f937e0fb1efe80cc3915732a161798d8961f959b914325d9336e |
| items/green-basket__potato.webp | photo-1784043436697-4458ec4097b7 | engin akyurt | https://unsplash.com/photos/freshly-harvested-potatoes-at-market-RlxdYtbF8kc | ab5c21f94d3a8fabceeedaa0025cf13f5658fcd06d53471fd79037b52db11038 |
| items/green-basket__carrot.webp | photo-1781863006581-8e3eeacba61d | Amar Preet Singh | https://unsplash.com/photos/a-large-pile-of-fresh-orange-carrots-btTM1GUDUnY | 7f29442e82d8c9c084ca1d94c49c5905533f0252c75bff1a3edfe9c00df4d4fa |
| items/green-basket__beans.webp | photo-1448293065296-c7e2e5b76ae9 | Mike Kenneally | https://unsplash.com/photos/bunch-of-green-beans-8eJPcAuqIhY | f89d689e9819c35017d3ac860509d78b9a06537b35b5fccc1d3402a0caedb66c |
| items/green-basket__capsicum.webp | photo-1585159079680-8dec029b76ed | Alli Stefanova | https://unsplash.com/photos/green-bell-pepper-on-brown-wooden-table-Er8w2PcHEXM | a6b19b4003b106698d1ea72e4f2358b11bec4e8bc2cafd4e91efae0ccfef70ea |
| items/green-basket__banana--yelakki.webp | photo-1587132137056-bfbf0166836e | Mockup Graphics | https://unsplash.com/photos/yellow-banana-on-white-background-Kl3467edwsE | d9a82fb4e08ef6aba87798320ad97753eff2d09e6f3cab35cba9a3c3fcaf8d8f |
| items/green-basket__papaya.webp | photo-1526318472351-c75fcf070305 | Bon Vivant | https://unsplash.com/photos/sliced-papaya-on-green-banana-leaf-Ooj1c6fhdFM | 14ca868fdcb912d58583314d80d8e1e4be71ccb8f9d87c039d237da71915c846 |
| items/green-basket__coconut.webp | photo-1560769680-ba2f3767c785 | Irene Kredenets | https://unsplash.com/photos/coconuts-on-white-surface-E95Lpkg-bgc | 6deb082096948e6178f6634782fb8d863cb2c122f0536f7f6ac4dbeac07ad9e8 |
| items/green-basket__coriander.webp | photo-1767156969831-0beee76fa958 | Rishabh Raj | https://unsplash.com/photos/fresh-green-cilantro-leaves-in-sunlight-Gx8WLeRRUEM | 27414a8c5bc3c9fbf8bc0d52709e204b8741553508611e71d62a57ad58cdfb8a |
