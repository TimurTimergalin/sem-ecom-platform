# Prototype schedule

Tasks and milestones from 17 September through 23 October 2026, in the order they start. A milestone is listed on the day it is due.

17 Sep:

- **FE-01 Shell** (through 22 Sep, frontend). Desktop layouts for the buyer, the seller, and sign-in, with shared buttons and empty states.
- **BC-01 Platform** (through 19 Sep, B2C). Docker Compose, PostgreSQL, Redis, health checks, and one shared error format.
- **BB-01 Schema** (through 19 Sep, B2B). Tables for the store, products, posts, images, the subscription, and delivery settings.
- **OR-01 Order model** (through 18 Sep, orders). Cart and order tables, plus the pickup and CDEK status list.

19 Sep:

- **M1 Platform boots.** Compose is up and the health checks pass.
- **OR-02 Cart storage** (through 21 Sep, orders). Add, change, and remove cart lines, and keep the price snapshot.

20 Sep:

- **BC-02 Yandex ID** (through 22 Sep, B2C). Sign-in through Yandex ID, a JWT for the APIs, and a dev user header.
- **BB-02 Onboarding** (through 22 Sep, B2B). An authenticated user creates one store with a unique username.

22 Sep:

- **M2 Sign-in and a store.** A person can sign in and register as a seller.

23 Sep:

- **FE-02 Login** (through 24 Sep, frontend). Yandex sign-in and registration screens, including the seller redirect.
- **BC-03 Profiles** (through 25 Sep, B2C). Buyer profile editing and the public master card.
- **BB-03 Store profile** (through 24 Sep, B2B). Edit the display name and bio. The username stays fixed.
- **OR-03 Order creation** (through 24 Sep, orders). Turn the cart into one order, ignore a repeated submit, and clear the cart.

25 Sep:

- **FE-03 Home** (through 26 Sep, frontend). Home feed of posts with linked product snippets.
- **BB-04 Media** (through 26 Sep, B2B). Image upload for a product, a post, and the store profile.
- **OR-04 Delivery options** (through 26 Sep, orders). Delivery choices and totals for checkout.

26 Sep:

- **BC-04 Page assembler** (through 28 Sep, B2C). One page response per screen. A failed side section does not blank the page.

27 Sep:

- **FE-04 Search** (frontend). Search page with tabs for posts, products, and sellers.
- **BB-05a Product create** (through 28 Sep, B2B). Create a product and list the products of the signed-in store.
- **OR-05 YooKassa** (through 4 Oct, orders). Sandbox safe deal, payment webhook, and cancel when payment is interrupted.

28 Sep:

- **M3 Product and unpaid order.** A product with an image exists, and a cart can become an order.
- **FE-05 Product page** (through 29 Sep, frontend). Gallery, price, stock, sale mode, and the seller card.

29 Sep:

- **BC-07 Product and master pages** (through 30 Sep, B2C). APIs for the product page and the public master page.
- **BB-05b Product edit** (through 1 Oct, B2B). Edit, delete, stock, sale mode, and filters in the seller's own catalog.

30 Sep:

- **FE-06 Master profile** (frontend). Public seller page and the publication page.

1 Oct:

- **FE-07 Cart** (through 2 Oct, frontend). Cart grouped by seller and delivery method, with quantity controls.
- **BC-10 Cart and checkout pages** (through 4 Oct, B2C). Page APIs for the cart, checkout, and the buyer's orders.

2 Oct:

- **BB-08 Delivery settings** (through 3 Oct, B2B). Pickup points with city and address, and a CDEK on/off switch.

3 Oct:

- **FE-08 Checkout** (through 6 Oct, frontend). Checkout screen and the return from YooKassa.

4 Oct:

- **BB-06 Quotas** (through 5 Oct, B2B). Free plan: 10 products, 5 posts, and no on-site payment. Premium is listed for comparison.

5 Oct:

- **BC-05 Home and publications** (through 6 Oct, B2C). APIs for the home feed and a publication page.
- **OR-06 Pickup fulfillment** (through 7 Oct, orders). Seller confirms stock, the buyer gets a pickup code, and the code closes the safe deal.

6 Oct:

- **M4 Buyer can pay.** A sandbox payment moves the order to paid.
- **BB-07 Publications** (through 9 Oct, B2B). Draft and publish a post, with the seller's products linked in order.

7 Oct:

- **FE-09 Buyer orders** (through 8 Oct, frontend). Buyer profile and the order list and detail.
- **BC-06 Search** (through 9 Oct, B2C). Product search in PostgreSQL.

8 Oct:

- **OR-07 Cancellations** (through 9 Oct, orders). Buyer or seller cancels. Stock is restored and a seller penalty is only recorded.

9 Oct:

- **M5 Discovery and pickup API.** Home and search read real data. A pickup code can close the deal through the API.
- **FE-10 Follow** (frontend). Follow button and the subscriptions page.

10 Oct:

- **FE-11 Seller shell** (through 11 Oct, frontend). Seller sidebar, onboarding checklist, profile, and the Free versus Premium page.
- **BC-08 Follow** (through 11 Oct, B2C). Follow and unfollow a master. Anonymous requests are rejected.
- **BB-10 Seller order facade** (through 12 Oct, B2B). Seller order list, and status changes sent to the order service.
- **OR-08 CDEK** (through 15 Oct, orders). Delivery quote, shipment registration, tracking, and payout in the CDEK sandbox.

12 Oct:

- **FE-12 Catalog UI** (through 13 Oct, frontend). Seller product list and the create/edit form, including the image.
- **BC-09 Events and recommendations** (through 14 Oct, B2C). Record views and cart events, and fill the home recommendations from follows and recency.

13 Oct:

- **BB-09 Dashboard** (through 14 Oct, B2B). Counts for new orders, followers, views, and low stock.

14 Oct:

- **FE-13 Post composer** (through 15 Oct, frontend). Write a post, attach the seller's products, and show a preview.

15 Oct:

- **BC-11 OpenAPI** (through 16 Oct, B2C). A rough API document for the page endpoints.
- **BB-11 Errors and OpenAPI** (through 17 Oct, B2B). Plain error responses and a short seller API document.

16 Oct:

- **FE-14 Seller orders** (through 17 Oct, frontend). Seller order list, pickup-code entry, and cancel.
- **OR-09 Premium charge** (through 17 Oct, orders). YooKassa charge for Premium. The plan changes only after payment is confirmed.

17 Oct:

- **BC-16 Repair and demo** (through 23 Oct, B2C). Fix the buyer path and connect the early screens to the live APIs.

18 Oct:

- **FE-15 Delivery and events** (through 19 Oct, frontend). Delivery settings screen and a few view and cart events.
- **BB-16 Repair and demo** (through 23 Oct, B2B). Fix the seller path used in the demo. Seed a store if the screens are still thin.
- **OR-16 Repair and demo** (through 23 Oct, orders). Rehearse pay, pickup close, and CDEK, and fix what breaks.

19 Oct:

- **M6 Rough feature complete.** The seller can close a pickup order on screen. A post links a product. CDEK and Premium work on the happy path.

20 Oct:

- **FE-16 Repair and demo** (through 23 Oct, frontend). Walk both journeys, fix what the script breaks, and write the gap list.

23 Oct:

- **M7 Demo.** Rehearsed buyer and seller demo, a short README, rough OpenAPI, and the gap list.

