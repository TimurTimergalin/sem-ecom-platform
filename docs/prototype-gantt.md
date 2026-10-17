# Handmade marketplace prototype

17 September through 23 October 2026, every day. Bar color is the owner. Dates on the axis are day/month. The Gantt chart does not draw arrows, so the cross-team waits and the milestone gates are in the second diagram. Work that stays inside one owner follows the bar order in that section.

```mermaid
%%{init: {"themeCSS": ".task0{fill:#242424 !important;stroke:#242424 !important}.task1{fill:#3B6D9A !important;stroke:#2A5174 !important}.task2{fill:#C47B2B !important;stroke:#8F5A1E !important}.task3{fill:#2E7D4F !important;stroke:#1F5A38 !important}.task4{fill:#6B4C9A !important;stroke:#4E3672 !important}.taskText4{fill:#fff !important}.section0{fill:#ececec !important}.section1{fill:#e7eef5 !important}.section2{fill:#f8efe4 !important}.section3{fill:#e7f2eb !important}.section4{fill:#f3eef8 !important;opacity:0.45 !important}"}}%%
gantt
    title Handmade marketplace prototype
    dateFormat YYYY-MM-DD
    axisFormat %d/%m
    todayMarker off

    section Milestones
    M1 Platform boots           :milestone, m1, 2026-09-19, 1d
    M2 Sign-in and store        :milestone, m2, 2026-09-22, 1d
    M3 Product and unpaid order :milestone, m3, 2026-09-28, 1d
    M4 Buyer can pay            :milestone, m4, 2026-10-06, 1d
    M5 Discovery and pickup API :milestone, m5, 2026-10-09, 1d
    M6 Rough feature complete   :milestone, m6, 2026-10-19, 1d
    M7 Demo                     :milestone, m7, 2026-10-23, 1d

    section Frontend
    FE-01 Shell                 :fe01, 2026-09-17, 6d
    FE-02 Login                 :fe02, 2026-09-23, 2d
    FE-03 Home                  :fe03, 2026-09-25, 2d
    FE-04 Search                :fe04, 2026-09-27, 1d
    FE-05 Product page          :fe05, 2026-09-28, 2d
    FE-06 Master profile        :fe06, 2026-09-30, 1d
    FE-07 Cart                  :fe07, 2026-10-01, 2d
    FE-08 Checkout              :fe08, 2026-10-03, 4d
    FE-09 Buyer orders          :fe09, 2026-10-07, 2d
    FE-10 Follow                :fe10, 2026-10-09, 1d
    FE-11 Seller shell          :fe11, 2026-10-10, 2d
    FE-12 Catalog UI            :fe12, 2026-10-12, 2d
    FE-13 Post composer         :fe13, 2026-10-14, 2d
    FE-14 Seller orders         :fe14, 2026-10-16, 2d
    FE-15 Delivery and events   :fe15, 2026-10-18, 2d
    FE-16 Repair and demo       :fe16, 2026-10-20, 4d

    section B2C backend
    BC-01 Platform              :bc01, 2026-09-17, 3d
    BC-02 Yandex ID             :bc02, 2026-09-20, 3d
    BC-03 Profiles              :bc03, 2026-09-23, 3d
    BC-04 Page assembler        :bc04, 2026-09-26, 3d
    BC-07 Product and master    :bc07, 2026-09-29, 2d
    BC-10 Cart and checkout     :bc10, 2026-10-01, 4d
    BC-05 Home and publications :bc05, 2026-10-05, 2d
    BC-06 Search                :bc06, 2026-10-07, 3d
    BC-08 Follow                :bc08, 2026-10-10, 2d
    BC-09 Events and recs       :bc09, 2026-10-12, 3d
    BC-11 OpenAPI               :bc11, 2026-10-15, 2d
    BC-16 Repair and demo       :bc16, 2026-10-17, 7d

    section B2B backend
    BB-01 Schema                :bb01, 2026-09-17, 3d
    BB-02 Onboarding            :bb02, 2026-09-20, 3d
    BB-03 Store profile         :bb03, 2026-09-23, 2d
    BB-04 Media                 :bb04, 2026-09-25, 2d
    BB-05a Product create       :bb05a, 2026-09-27, 2d
    BB-05b Product edit         :bb05b, 2026-09-29, 3d
    BB-08 Delivery settings     :bb08, 2026-10-02, 2d
    BB-06 Quotas                :bb06, 2026-10-04, 2d
    BB-07 Publications          :bb07, 2026-10-06, 4d
    BB-10 Seller order facade   :bb10, 2026-10-10, 3d
    BB-09 Dashboard             :bb09, 2026-10-13, 2d
    BB-11 Errors and OpenAPI    :bb11, 2026-10-15, 3d
    BB-16 Repair and demo       :bb16, 2026-10-18, 6d

    section Orders and payments
    OR-01 Order model           :or01, 2026-09-17, 2d
    OR-02 Cart storage          :or02, 2026-09-19, 3d
    OR-03 Order creation        :or03, 2026-09-22, 3d
    OR-04 Delivery options      :or04, 2026-09-25, 2d
    OR-05 YooKassa              :or05, 2026-09-27, 8d
    OR-06 Pickup fulfillment    :or06, 2026-10-05, 3d
    OR-07 Cancellations         :or07, 2026-10-08, 2d
    OR-08 CDEK                  :or08, 2026-10-10, 6d
    OR-09 Premium charge        :or09, 2026-10-16, 2d
    OR-16 Repair and demo       :or16, 2026-10-18, 6d
```

## Dependencies

An arrow means the target cannot finish its job until the source is done. Same-owner sequences are left off this chart. They are the consecutive bars in each Gantt section.

```mermaid
flowchart LR
    classDef fe fill:#3B6D9A,color:#fff,stroke:#3B6D9A
    classDef b2c fill:#C47B2B,color:#fff,stroke:#C47B2B
    classDef b2b fill:#2E7D4F,color:#fff,stroke:#2E7D4F
    classDef ord fill:#6B4C9A,color:#fff,stroke:#6B4C9A
    classDef ms fill:#242424,color:#fff,stroke:#242424

    BC01["<font color=white>BC-01 Platform</font>"]:::b2c --> BB02["<font color=white>BB-02 Onboarding</font>"]:::b2b
    BC01 --> OR02["<font color=white>OR-02 Cart</font>"]:::ord
    BC01 --> FE02["<font color=white>FE-02 Login</font>"]:::fe
    BC02["<font color=white>BC-02 Yandex ID</font>"]:::b2c --> FE02
    BB02 --> FE11["<font color=white>FE-11 Seller shell</font>"]:::fe

    BB05a["<font color=white>BB-05a Product create</font>"]:::b2b --> BC07["<font color=white>BC-07 Product page</font>"]:::b2c
    BB05b["<font color=white>BB-05b Product edit</font>"]:::b2b --> BC05["<font color=white>BC-05 Home</font>"]:::b2c
    BB05b --> BC06["<font color=white>BC-06 Search</font>"]:::b2c
    BB05b --> FE12["<font color=white>FE-12 Catalog UI</font>"]:::fe

    OR02 --> FE07["<font color=white>FE-07 Cart</font>"]:::fe
    OR02 --> BC10["<font color=white>BC-10 Checkout API</font>"]:::b2c
    OR03["<font color=white>OR-03 Order create</font>"]:::ord --> BC10
    OR04["<font color=white>OR-04 Delivery options</font>"]:::ord --> BB08["<font color=white>BB-08 Delivery settings</font>"]:::b2b
    OR04 --> OR08["<font color=white>OR-08 CDEK</font>"]:::ord
    BB08 --> OR06["<font color=white>OR-06 Pickup</font>"]:::ord
    BB08 --> OR08
    BB08 --> FE15["<font color=white>FE-15 Delivery screen</font>"]:::fe
    OR05["<font color=white>OR-05 YooKassa</font>"]:::ord --> FE08["<font color=white>FE-08 Checkout</font>"]:::fe
    BC10 --> FE09["<font color=white>FE-09 Buyer orders</font>"]:::fe

    BB06["<font color=white>BB-06 Quotas</font>"]:::b2b --> OR09["<font color=white>OR-09 Premium</font>"]:::ord
    BB07["<font color=white>BB-07 Publications</font>"]:::b2b --> BC09["<font color=white>BC-09 Events</font>"]:::b2c
    BB07 --> FE13["<font color=white>FE-13 Post composer</font>"]:::fe
    OR06 --> BB10["<font color=white>BB-10 Order facade</font>"]:::b2b
    OR07["<font color=white>OR-07 Cancellations</font>"]:::ord --> BB10
    BC08["<font color=white>BC-08 Follow</font>"]:::b2c --> BB09["<font color=white>BB-09 Dashboard</font>"]:::b2b
    BB10 --> FE14["<font color=white>FE-14 Seller orders</font>"]:::fe
    FE13 --> FE15
    FE14 --> FE15

    BC01 --> M1(["<font color=white>M1 Platform</font>"]):::ms
    BB01["<font color=white>BB-01 Schema</font>"]:::b2b --> M1
    OR01["<font color=white>OR-01 Model</font>"]:::ord --> M1
    BC02 --> M2(["<font color=white>M2 Sign-in</font>"]):::ms
    BB02 --> M2
    BB05a --> M3(["<font color=white>M3 Product</font>"]):::ms
    OR03 --> M3
    FE08 --> M4(["<font color=white>M4 Paid checkout</font>"]):::ms
    OR05 --> M4
    BC10 --> M4
    BC06 --> M5(["<font color=white>M5 Discovery</font>"]):::ms
    BB07 --> M5
    OR06 --> M5
    FE15 --> M6(["<font color=white>M6 Feature complete</font>"]):::ms
    OR08 --> M6
    OR09 --> M6
    FE16["<font color=white>FE-16 Repair</font>"]:::fe --> M7(["<font color=white>M7 Demo</font>"]):::ms
    BC16["<font color=white>BC-16 Repair</font>"]:::b2c --> M7
    BB16["<font color=white>BB-16 Repair</font>"]:::b2b --> M7
    OR16["<font color=white>OR-16 Repair</font>"]:::ord --> M7
    M1 --> M2 --> M3 --> M4 --> M5 --> M6 --> M7
```
