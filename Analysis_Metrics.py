import pandas as pd
import os
import json
from bs4 import BeautifulSoup
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from nltk.util import ngrams

# === CONFIGURATION ===
input_path = "Gannett_perplexity_2024-06-07.csv"  # Change this to your file
# allowable file names: Gannett_[model]_[YYYY]-[MM]-[DD].csv or Gannett_[model]_[YYYY]-[MM]-[DD]_[DD].csv to specify a range

min_word_threshold = 50
fixed_sections = [
    "sports", "news", "business", "politics", "entertainment", "opinion", "nation", "local",
    "crime", "education", "investigations", "world", "obituaries", "lifestyle", "weather",
    "travel", "food", "health", "technology"
]

# === Metadata Extraction ===
def extract_model_and_date(filename):
    name = os.path.basename(filename).replace(".csv", "").lower()
    parts = name.split("_")
    
    model = parts[1] if len(parts) > 1 else "unknown"

    # Special case handling for model name corrections
    if model == "gpt":
        model = "chatgpt"
    
    date_part = parts[-1]
    if len(parts) >= 3 and "-" in parts[-2]:
        date_part = parts[-2] + "_" + parts[-1]

    if "miscellaneous" in name:
        date_label = "miscellaneous"
    elif "_" in date_part:
        start_date, end_day = date_part.split("_")
        year, month, start_day = start_date.split("-")
        date_label = f"{year}-{month}-{start_day} to {year}-{month}-{end_day}"
    else:
        date_label = date_part

    return model, date_label

model, date_label = extract_model_and_date(input_path)
df = pd.read_csv(input_path)

# === Cleaning ===
def clean_html(text):
    if pd.isna(text):
        return ""
    text = BeautifulSoup(text, "html.parser").get_text(separator=" ").strip()
    return text.replace("\u200b", "")

df["clean_response"] = df["response_text"].apply(clean_html)
df["clean_article_text"] = df["fullText"].apply(clean_html)

# === Filtering ===
initial_count = len(df)
df = df[~df["clean_response"].isna() & (df["clean_response"].str.strip() != "")]
filtered_wordcount = df[df["clean_response"].str.split().str.len() < min_word_threshold]
removed_short = len(filtered_wordcount)
df = df[df["clean_response"].str.split().str.len() >= min_word_threshold]

filter_keywords = [
    "can't provide", "cannot provide", "i don't know", "i'm sorry",
    "i am sorry", "cannot access", "unable to provide", "i apologize"
]
df = df[~df["clean_response"].str.lower().str.contains('|'.join(filter_keywords))]
df = df[df["prompt"].str.count("Tell me about") <= 1] if "prompt" in df.columns else df

df = df.reset_index(drop=True)

# === Cosine Similarity ===
vectorizer = TfidfVectorizer(stop_words="english")
cos_sim = []
for _, row in df.iterrows():
    tfidf = vectorizer.fit_transform([row["clean_article_text"], row["clean_response"]])
    cos_sim.append(cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0])
df["cosine_similarity"] = cos_sim

# === N-gram Similarity ===
def simple_tokenize(text):
    return text.lower().split()

def ngram_match_score(text1, text2, n):
    tokens1 = simple_tokenize(text1)
    tokens2 = simple_tokenize(text2)
    ngrams1 = list(ngrams(tokens1, n))
    ngrams2 = list(ngrams(tokens2, n))
    if not ngrams1:
        return 0.0
    matches = sum(1 for gram in ngrams1 if gram in ngrams2)
    return matches / len(ngrams1)

df["bigram_match"] = [ngram_match_score(row["clean_article_text"], row["clean_response"], 2) for _, row in df.iterrows()]
df["trigram_match"] = [ngram_match_score(row["clean_article_text"], row["clean_response"], 3) for _, row in df.iterrows()]

# === Source Count ===
if model == "chatgpt":
    def count_sources(row):
        try:
            citations = json.loads(row.get("response_citations", "[]"))
            return len(citations)
        except:
            return 0
    df["source_count"] = df.apply(count_sources, axis=1)
elif model == "perplexity":
    if "number_of_sources" in df.columns:
        df["source_count"] = df["number_of_sources"]
    else:
        df["source_count"] = pd.NA
else:
    df["source_count"] = pd.NA

# === Section Averages for Fixed List ===
section_avgs = {}
for sec in fixed_sections:
    if sec in df["section"].dropna().unique():
        subset = df[df["section"] == sec]
        section_avgs[f"{sec}_avg_cosine"] = subset["cosine_similarity"].mean()
        section_avgs[f"{sec}_avg_bigram"] = subset["bigram_match"].mean()
        section_avgs[f"{sec}_avg_trigram"] = subset["trigram_match"].mean()
    else:
        section_avgs[f"{sec}_avg_cosine"] = "NA"
        section_avgs[f"{sec}_avg_bigram"] = "NA"
        section_avgs[f"{sec}_avg_trigram"] = "NA"

# === Bucketed Metrics ===
def get_bucketed_distribution(series, bins):
    return pd.cut(series, bins=bins).value_counts(normalize=True, sort=False) * 100

cosine_buckets = get_bucketed_distribution(df["cosine_similarity"], bins=[0.0, 0.5, 0.75, 1.0])
bigram_buckets = get_bucketed_distribution(df["bigram_match"], bins=[0.0, 0.1, 0.25, 1.0])
trigram_buckets = get_bucketed_distribution(df["trigram_match"], bins=[0.0, 0.05, 0.15, 1.0])

# === Source Presence Metrics ===
if model == "chatgpt":
    original_source_pct = df.get("original_in_citations", 0).fillna(0).astype(int).mean() * 100
    any_source_pct = (
        df[["original_in_citations", "original_in_search_results", "republisher_in_citations", "republisher_in_search_results"]]
        .fillna(0).astype(int).any(axis=1).mean() * 100
    )
elif model == "perplexity":
    original_source_pct = df.get("original_in_sources", 0).fillna(0).astype(int).mean() * 100
    any_source_pct = "NA"
else:
    original_source_pct = "NA"
    any_source_pct = "NA"

# === Final Metrics Row ===
overall_summary = {
    "model": model,
    "date": date_label,
    "total_articles": initial_count,
    "removed_short": removed_short,
    "final_rows": len(df),
    "avg_cosine": df["cosine_similarity"].mean(),
    "median_cosine": df["cosine_similarity"].median(),
    "min_cosine": df["cosine_similarity"].min(),
    "max_cosine": df["cosine_similarity"].max(),
    "avg_bigram": df["bigram_match"].mean(),
    "median_bigram": df["bigram_match"].median(),
    "min_bigram": df["bigram_match"].min(),
    "max_bigram": df["bigram_match"].max(),
    "avg_trigram": df["trigram_match"].mean(),
    "median_trigram": df["trigram_match"].median(),
    "min_trigram": df["trigram_match"].min(),
    "max_trigram": df["trigram_match"].max(),
    "avg_source_count": df["source_count"].mean() if df["source_count"].notna().any() else "NA",
    "median_source_count": df["source_count"].median() if df["source_count"].notna().any() else "NA",
    "original_source_present_pct": original_source_pct,
    "any_source_present_pct": any_source_pct,
    "cosine_<0.5_pct": cosine_buckets.iloc[0],
    "cosine_0.5–0.75_pct": cosine_buckets.iloc[1],
    "cosine_>0.75_pct": cosine_buckets.iloc[2],
    "bigram_<0.1_pct": bigram_buckets.iloc[0],
    "bigram_0.1–0.25_pct": bigram_buckets.iloc[1],
    "bigram_>0.25_pct": bigram_buckets.iloc[2],
    "trigram_<0.05_pct": trigram_buckets.iloc[0],
    "trigram_0.05–0.15_pct": trigram_buckets.iloc[1],
    "trigram_>0.15_pct": trigram_buckets.iloc[2],
}

summary = {**overall_summary, **section_avgs}

summary_df = pd.DataFrame([summary])

# === Output file named based on model and date
output_file = f"analysis_summary_{model}_{date_label}.csv"
if os.path.exists(output_file):
    existing_df = pd.read_csv(output_file)
    summary_df = pd.concat([existing_df, summary_df], ignore_index=True)
summary_df.to_csv(output_file, index=False)
