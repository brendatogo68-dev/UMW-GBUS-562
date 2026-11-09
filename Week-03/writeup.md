## What I Built

I built a retrieval-augmented generation (RAG) tool using Chroma and Claude to answer questions from a collection of documents. The tool reads documents, creates embeddings, retrieves the most relevant chunks, and uses Claude to generate answers based only on the retrieved sources.

To support Larkfield's documents, I used the --docs option to select the larkfield-docs folder and the --save option to save results to text files. I also removed the outdated consumer-fee-schedule-v7.html document from the indexed document collection and rebuilt the database so retrieval would use only the current fee schedule.

I completed nine saved runs: q1-before.txt, q1-after.txt, q2-before.txt, q2-after.txt, q2.txt, q3.txt, q4.txt, q5.txt, and q6.txt.

## Why This Approach

Chunking method: structure

Makes sense on its own: Yes. Each chunk starts with the document title and section heading, and some chunks include additional context notes. This helps the chunk make sense when read by itself.

Label and source: Both. The chunks carry the document title and section heading in the chunk text, and the source file is stored in the metadata and shown in retrieval results.

Short enough: Yes. The tool splits sections into parts of at most about 180 words, which is short enough for the embedding model to read in full.

## Example Run

```text
1. similarity 0.707 | consumer-fee-schedule.html
   Document: Consumer Fee Schedule Section: Overdraft and returned item fees When Larkfield pays a check, debit card purchase, or automatic payment that ...
2. similarity 0.639 | consumer-fee-schedule.html
   Document: Consumer Fee Schedule Section: Checking account monthly fees Everyday Checking has no monthly service fee. Plus Checking has a monthly servi...
3. similarity 0.566 | consumer-fee-schedule.html
   Document: Consumer Fee Schedule Section: Dormant accounts An account with no member-initiated activity for 24 months becomes dormant. A dormant accoun...
4. similarity 0.541 | consumer-fee-schedule.html
   Document: Consumer Fee Schedule Section: Stop payments A stop payment on a check costs $30 per request. One request can cover a single check or a seri...

ANSWER
The overdraft fee is $29 per item paid, with a maximum of three overdraft or returned item fees per account per business day [consumer-fee-schedule.html]. However, no overdraft fee is charged if the account is overdrawn by $10 or less at the end of the business day [consumer-fee-schedule.html].
```

## Reflection

What was wrong: The document that caused the problem was consumer-fee-schedule-v7.html. The retrieved chunks for Question 1 included both consumer-fee-schedule.html and consumer-fee-schedule-v7.html, causing duplicate and potentially outdated fee information to be retrieved.

How I fixed it: Removed consumer-fee-schedule-v7.html from the indexed document collection by moving it to larkfield-docs-archive. I then rebuilt the Chroma database so retrieval would use only the current fee schedule documents.

Prevention: Archive process. Larkfield should move superseded documents into an archive location before indexing so that outdated versions cannot compete with current documents during retrieval.

Question 6: Declined. The tool correctly reported that the documents did not contain information about the current 30-year fixed mortgage rate. Retrieval returned chunks from the document collection, but none contained a mortgage rate, so the tool followed its instructions and answered that the information was not covered.
