# Sample API Queries

## Example 1: Find Stories by Keyword

**Description:** Search for assets based on keywords and types

### Query

```json
query{
  searchAssets(template: "asset_keyword_by_types", parameters: "{\"site_codes\":[\"USAT\",\"PPHX\"],\"types\":[\"text\"],\"query\":\"\\"is one of USA TODAY’s Women of the Year\\"\",\"size\": 24}") {
    assets {
      headline
      ... on text {
        fullText
      }
      type
      publishDate
      pageURL {
        long
      }
    }
  }
}
```

### Sample Query URL

[GraphiQL Query Link](https://content-api.gannettdigital.com/graphiql?siteCode=USAT\&type=asset\&environment=production\&query=query%7B%20searchAssets%28template%3A%20%22asset_keyword_by_types%22%2C%20parameters%3A%20%22%7B%5C%22site_codes%5C%22%3A%5B%5C%22USAT%5C%22%2C%5C%22PPHX%5C%22%5D%2C%5C%22types%5C%22%3A%5B%5C%22text%5C%22%5D%2C%5C%22query%5C%22%3A%5C%22%5C%5C%5C%22is%20one%20of%20USA%20TODAY%E2%80%99s%20Women%20of%20the%20Year%5C%5C%5C%22%5C%22%2C%5C%22size%5C%22%3A%2024%7D%22%29%20%7B%20assets%20%7B%20headline%20...%20on%20text%20%7B%20fullText%20%7D%20type%20publishDate%20pageURL%20%7B%20long%20%7D%20%7D%20%7D%20%7D)

### cURL Command

```sh
curl --request POST \
  --url https://content-api.gannettdigital.com/assets \
  --compressed \
  --header 'Accept-Encoding: gzip, deflate' \
  --header 'Cache-Control: max-age=0' \
  --header 'Content-Type: application/graphql' \
  --header 'Host: content-api.gannettdigital.com' \
  --header 'content-type: application/json' \
  --header 'x-api-key: YOUR_API_KEY' \
  --header 'x-sitecode: USAT' \
  --data 'query{
  searchAssets(template: "asset_keyword_by_types", parameters: "{\"site_codes\":[\"USAT\",\"PPHX\"],\"types\":[\"text\"],\"query\":\"\\\"is one of USA TODAY’s Women of the Year\\\"\",\"size\": 24}") {
    assets {
      headline
      ... on text {
        fullText
      }
      type
      publishDate
      pageURL {
        long
      }
    }
  }
}'
```

---

## Example 2: Find Stories by Section

**Description:** Search for assets based on sections and topics

### Query

```json
query{
  searchAssets(template: "asset_keyword_by_types", parameters: "{\"site_codes\":[\"USAT\",\"PPHX\"],\"types\":[\"text\"],\"query\":\"\\"is one of USA TODAY’s Women of the Year\\"\",\"size\": 24}") {
    assets {
      headline
      ... on text {
        fullText
      }
      type
      publishDate
      pageURL {
        long
      }
    }
  }
}
```

### Sample Query URL

[GraphiQL Query Link](https://content-api.gannettdigital.com/graphiql?siteCode=USAT\&type=asset\&environment=production\&query=query%7B%20searchAssets%28template%3A%20%22asset_keyword_by_types%22%2C%20parameters%3A%20%22%7B%5C%22site_codes%5C%22%3A%5B%5C%22USAT%5C%22%2C%5C%22PPHX%5C%22%5D%2C%5C%22types%5C%22%3A%5B%5C%22text%5C%22%5D%2C%5C%22query%5C%22%3A%5C%22%5C%5C%5C%22is%20one%20of%20USA%20TODAY%E2%80%99s%20Women%20of%20the%20Year%5C%5C%5C%22%5C%22%2C%5C%22size%5C%22%3A%2024%7D%22%29%20%7B%20assets%20%7B%20headline%20...%20on%20text%20%7B%20fullText%20%7D%20type%20publishDate%20pageURL%20%7B%20long%20%7D%20%7D%20%7D%20%7D)

### cURL Command

```sh
curl --request POST \
  --url https://content-api.gannettdigital.com/assets \
  --compressed \
  --header 'Accept-Encoding: gzip, deflate' \
  --header 'Cache-Control: max-age=0' \
  --header 'Content-Type: application/graphql' \
  --header 'Host: content-api.gannettdigital.com' \
  --header 'content-type: application/json' \
  --header 'x-api-key: YOUR_API_KEY' \
  --header 'x-sitecode: USAT' \
  --data 'query{
  searchAssets(template: "asset_recent_by_site", parameters: "{\"site_codes\":[\"USAT\"],\"types\":[\"text\"],\"size\": 24}") {
    assets {
      headline
      ... on text {
        fullText
      }
      type
      publishDate
      pageURL {
        long
      }
    }
  }
}'
```

---

## Example 4: Find Stories on a Specific Site on a Specific Day

**Description:** Retrieve newest initial published non-sponsored stories from a given site within a start/end date range

### Query

```json
query{
  searchAssets(template: "asset_on_day_by_site", parameters: "{\"types\":[\"text\"],\"site_code\":\"NPRJ\",\"start_date\":\"2024-11-01\",\"end_date\":\"2024-11-02\"}") {
    assets {
      headline
      ... on text {
        fullText
      }
      type
      publishDate
      pageURL {
        long
      }
    }
  }
}
```

### Sample Query URL

[GraphiQL Query Link](https://content-api.gannettdigital.com/assets?query=query%20%7B%0A%20%20searchAssets%28template%3A%20%22asset_on_day_by_site%22%2C%20parameters%3A%20%22%7B%5C%22types%5C%22%3A%5B%5C%22text%5C%22%5D%2C%5C%22site_code%5C%22%3A%5C%22NPRJ%5C%22%2C%5C%22start_date%5C%22%3A%5C%222024-11-01%5C%22%2C%5C%22end_date%5C%22%3A%5C%222024-11-02%5C%22%7D%22%29%20%7B%0A%20%20%20%20assets%20%7B%0A%20%20%20%20%20%20headline%0A%20%20%20%20%20%20...%20on%20text%20%7B%0A%20%20%20%20%20%20%20%20fullText%0A%20%20%20%20%20%20%7D%0A%20%20%20%20%20%20type%0A%20%20%20%20%20%20publishDate%0A%20%20%20%20%20%20pageURL%20%7B%0A%20%20%20%20%20%20%20%20long%0A%20%20%20%20%20%20%7D%0A%20%20%20%20%7D%0A%20%20%7D%0A%7D)

**Description:** Retrieve stories from a given site within a date range

### cURL Command

```sh
curl --request POST \
  --url https://content-api.gannettdigital.com/assets \
  --compressed \
  --header 'Accept-Encoding: gzip, deflate' \
  --header 'Cache-Control: max-age=0' \
  --header 'Content-Type: application/graphql' \
  --header 'Host: content-api.gannettdigital.com' \
  --header 'content-type: application/json' \
  --header 'x-api-key: YOUR_API_KEY' \
  --header 'x-sitecode: USAT' \
  --data 'query{
  searchAssets(template: "asset_on_day_by_site", parameters: "{\"types\":[\"text\"],\"site_code\":\"NPRJ\",\"start_date\":\"2024-11-01\",\"end_date\":\"2024-11-02\"}") {
    assets {
      headline
      ... on text {
        fullText
      }
      type
      publishDate
      pageURL {
        long
      }
    }
  }
}'
```

