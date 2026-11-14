# Retrieval results (automatic)

## dev

| Strategy | Hit@1 | Evidence Hit@3 | Page hit@3 (diagnostic) | Metadata auto-OK | Filter compliance | Misses |
|---|---|---|---|---|---|---|
| A | 11/15 (73%) | 12/15 (80%) | 15/15 (100%) | 45/45 (100%) | N/A (no filter applied) | d04, d07, d11 |
| B | 14/15 (93%) | 15/15 (100%) | 15/15 (100%) | 45/45 (100%) | N/A (no filter applied) | - |
| C | 14/15 (93%) | 15/15 (100%) | 15/15 (100%) | 45/45 (100%) | 3/3 (100%) | - |

## test

| Strategy | Hit@1 | Evidence Hit@3 | Page hit@3 (diagnostic) | Metadata auto-OK | Filter compliance | Misses |
|---|---|---|---|---|---|---|
| A | 4/5 (80%) | 4/5 (80%) | 5/5 (100%) | 15/15 (100%) | N/A (no filter applied) | t03 |
| B | 4/5 (80%) | 4/5 (80%) | 5/5 (100%) | 15/15 (100%) | N/A (no filter applied) | t03 |
| C | 4/5 (80%) | 4/5 (80%) | 5/5 (100%) | 15/15 (100%) | 2/2 (100%) | t03 |

## all

| Strategy | Hit@1 | Evidence Hit@3 | Page hit@3 (diagnostic) | Metadata auto-OK | Filter compliance | Misses |
|---|---|---|---|---|---|---|
| A | 15/20 (75%) | 16/20 (80%) | 20/20 (100%) | 60/60 (100%) | N/A (no filter applied) | d04, d07, d11, t03 |
| B | 18/20 (90%) | 19/20 (95%) | 20/20 (100%) | 60/60 (100%) | N/A (no filter applied) | t03 |
| C | 18/20 (90%) | 19/20 (95%) | 20/20 (100%) | 60/60 (100%) | 5/5 (100%) | t03 |

## Per question (first hit rank; `-` = no full-evidence chunk in top-3, `p` = right page only)

| id | split | type | filter | A | B | C |
|---|---|---|---|---|---|---|
| d01 | dev | truc_tiep |  | 1 | 1 | 1 |
| d02 | dev | truc_tiep |  | 1 | 1 | 1 |
| d03 | dev | dieu_kien |  | 1 | 1 | 1 |
| d04 | dev | dien_dat_lai |  | p | 1 | 1 |
| d05 | dev | dieu_kien |  | 2 | 2 | 2 |
| d06 | dev | truc_tiep |  | 1 | 1 | 1 |
| d07 | dev | dieu_kien |  | p | 1 | 1 |
| d08 | dev | dien_dat_lai |  | 1 | 1 | 1 |
| d09 | dev | truc_tiep |  | 1 | 1 | 1 |
| d10 | dev | dien_dat_lai |  | 1 | 1 | 1 |
| d11 | dev | dieu_kien |  | p | 1 | 1 |
| d12 | dev | filter | B.II | 1 | 1 | 1 |
| d13 | dev | filter | B.II | 1 | 1 | 1 |
| d14 | dev | filter | A | 1 | 1 | 1 |
| d15 | dev | truc_tiep |  | 1 | 1 | 1 |
| t01 | test | filter | B.I | 1 | 1 | 1 |
| t02 | test | truc_tiep |  | 1 | 1 | 1 |
| t03 | test | dieu_kien |  | p | p | p |
| t04 | test | filter | B.II | 1 | 1 | 1 |
| t05 | test | dieu_kien |  | 1 | 1 | 1 |
