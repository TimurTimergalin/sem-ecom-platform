# Requirements to tasks

Each row is one requirement or a consecutive range that lands on the same tasks.

| Requirement | Tasks | What the task delivers |
|---|---|---|
| REQ-4.1.1-01..03, 06..10 | BC-04 | B2C is the only buyer API. Page assembly, section status, 404 for a missing main entity. |
| REQ-4.1.1-04..05 | BC-01 | Unified error JSON and `X-Request-Id`. |
| REQ-4.1.2-01..05, 07..09 | BC-05, FE-03 | Home page sections and the buyer feed. |
| REQ-4.1.2-06 | BC-09 | Recommendations from follows, recency, and popularity. Gorse is not built. |
| REQ-4.1.3-01..06 | BC-06, FE-04 | Search, facets, and result order. PostgreSQL `tsvector`, not MeiliSearch. |
| REQ-4.1.3-07 | BC-09, FE-04 | A search event can be sent. |
| REQ-4.1.4-01..06 | BC-05, BC-09, FE-06 | Publication feed and detail. The product strip can fail without hiding the text. |
| REQ-4.1.5-01..03, 05..06 | BC-07, FE-05 | Product page. A missing product is 404. Similar items and in-cart flag. |
| REQ-4.1.5-04 | BC-03, BC-07 | Master block on the product page. |
| REQ-4.1.5-07..09 | BC-07, FE-06, BC-08 | Master page and follow from that page. |
| REQ-4.1.6-01..06 | BC-08, FE-10 | Subscription list, follow, and unfollow. Anonymous access is 401. |
| REQ-4.1.7-01..06, 08 | OR-02, BC-10, FE-07 | Cart lines, totals, and the price snapshot. |
| REQ-4.1.7-07 | BC-09, FE-15 | Add-to-cart event. |
| REQ-4.1.8-01..02 | BC-10, OR-04, FE-08 | Checkout page: cart, addresses, delivery options, totals. |
| REQ-4.1.8-03..06 | OR-03, BC-10 | Create the order from cart snapshots, pass `Idempotency-Key`, clear the cart. |
| REQ-4.1.8-07..09 | BC-10, FE-09 | Order success, list, and detail, only for the owner. |
| REQ-4.1.8-10 | OR-05 | Payment is the YooKassa sandbox, not a stub. |
| REQ-4.1.8-11 | BC-09 | Purchase event for recommendations. |
| REQ-4.1.9-01..07 | BC-09, FE-15 | `POST /events` into Redis. Kafka, a separate eventer, and Gorse are not built. |
| REQ-4.1.10-01..05 | BC-02, FE-02 | Public pages stay open. Cart, checkout, orders, and follow require a user. JWT in the demo, dev header only when enabled. |
| REQ-4.1.11-01..02 | BC-04, BC-16 | Upstream timeout and retries. A failed read degrades a section instead of failing the page. |
| REQ-4.1.12-01 | BC-11 | Rough OpenAPI for the page models. |
| REQ-4.1.12-02 | BC-04 | Contracts stay on `/api/v1`. |
| REQ-4.1.12-03..04 | BC-01 | Health endpoints and logs with request id. |
| REQ-4.1.12-05 | — | No timed latency check. The suggested p95 target stays open. |
| REQ-4.2.1-01..14 | BB-02 | Seller role check, one store, unique username, no duplicate registration. |
| REQ-4.2.1-15..16 | BB-02, FE-11 | Onboarding checklist, reopenable later. |
| REQ-4.2.2-01..02, 04..08 | BB-03, FE-11 | Read and edit the store. Username is immutable. Link to the public page. |
| REQ-4.2.2-03 | BB-04, FE-11 | Upload and replace the store image. |
| REQ-4.2.3-01..03, 06..07 | BB-05a, FE-12 | Create, list, and read products bound to the caller's store. |
| REQ-4.2.3-04..05, 08..16 | BB-05b, FE-12 | Edit, delete, stock, sale mode, filters, and pagination. A deleted product stays linked but unavailable. |
| REQ-4.2.4-01..15 | BB-07, FE-13 | Create, draft, publish, and delete posts. Link the seller's own products in order. |
| REQ-4.2.5-01..07 | BB-04, FE-12, FE-13 | Image upload, type and size checks, and a reference only after a successful store. |
| REQ-4.2.6-01..05, 09 | BB-06, FE-11 | Free limits and the plan comparison. Premium analytics and search boost are shown and not built. |
| REQ-4.2.6-06..08 | OR-09, BB-06 | Premium starts only after the YooKassa webhook. A failed charge leaves Free in place. |
| REQ-4.2.7-01..17 | BB-09, FE-11 | Dashboard for this store only: orders, followers, views, low stock. An outage is not shown as zero. |
| REQ-4.2.8-01..09 | BB-10, FE-14, OR-06 | Seller order list and status actions. The order service stays the source of truth. |
| REQ-4.2.9-01..05 | BB-08, FE-15 | Pickup and CDEK toggles. Pickup fields are city and address. |
| REQ-4.2.10-01..09 | BB-05b, BB-11 | 401, 403, 404, and validation errors. A rejected write keeps the previous values. |
| REQ-4.3-01, 14 | OR-03 | Create a pickup order and a CDEK order from checkout. |
| REQ-4.3-02..03, 09..10 | OR-05 | Safe deal, payment, payout update, and cancel when payment stops. |
| REQ-4.3-04..08 | OR-06 | Stock confirmation, ready state, pickup code, and close of the safe deal. |
| REQ-4.3-11..13 | OR-07 | Buyer and seller cancellation. Stock is restored. The penalty is recorded, not collected. |
| REQ-4.3-15..21 | OR-08 | CDEK quote, invoice, shipment, tracking, pickup detection, and payout. |
| REQ-4.3-22 | — | No admin order console. Administrators are out of this release. |
| REQ-4.3-23 | OR-16 | Returns stay a direct buyer-seller matter, as the requirement says. |
| REQ-5.1-01..02 | — | No timed check that home and the feed load within 3 seconds. |
| REQ-5.1-03 | BC-06 | Search is built. The 2 second target is not measured. |
| REQ-5.1-04 | BB-06 | Free plan allows 10 products, inside the stated 10 to 15. |
| REQ-5.1-05 | — | No test for 100 concurrent users. |
| REQ-5.2-01..02 | BB-01, BB-07 | A publish status exists. There is no moderator queue. |
| REQ-5.2-03..06 | — | Moderator accept, reject, and hide are a separate SRS. |
| REQ-5.2-07..08 | BB-06, FE-05 | Free-plan products are deal-only, with a notice to contact the seller. |
| REQ-5.3-01..02 | OR-05 | Paid-plan payments go through YooKassa. The seller connects a sandbox shop. |
| REQ-5.3-03 | BC-02, FE-02 | Buyer entry is Yandex ID. No password is stored. |
| REQ-5.3-04 | OR-03, BC-10, FE-09 | Order history is behind authentication and an ownership check. |
| REQ-5.3-05 | BC-08, FE-10 | Follow and the subscriptions page require a signed-in buyer. |
| REQ-5.3-06..07 | — | There is no messaging feature, so no message can be exposed. |
| REQ-5.3-08 | BC-01 | Client and server traffic is HTTPS. |
