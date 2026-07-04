# Oyente+ metrics (reproducible Docker run)

| Dataset | Vulnerability | TP | FP | TN | FN | Precision % | Recall % | F1 % | Accuracy % |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|
| sbc | overflow | 13 | 101 | 25 | 2 | 11.4 | 86.7 | 20.2 | 27.0 |
| sbc | reentrancy | 29 | 9 | 101 | 2 | 76.3 | 93.5 | 84.1 | 92.2 |
| sbc | timestamp | 11 | 2 | 125 | 3 | 84.6 | 78.6 | 81.5 | 96.5 |
| sbc | tod | 2 | 35 | 102 | 2 | 5.4 | 50.0 | 9.8 | 73.8 |
| solidifi | tod | 36 | 4 | 46 | 14 | 90.0 | 72.0 | 80.0 | 82.0 |
| rsd | reentrancy | 41 | 30 | 41 | 24 | 57.7 | 63.1 | 60.3 | 60.3 |
| qian | overflow | 63 | 46 | 143 | 23 | 57.8 | 73.3 | 64.6 | 74.9 |
| qian | reentrancy | 61 | 73 | 80 | 8 | 45.5 | 88.4 | 60.1 | 63.5 |
| qian | timestamp | 1 | 15 | 160 | 172 | 6.2 | 0.6 | 1.1 | 46.3 |
