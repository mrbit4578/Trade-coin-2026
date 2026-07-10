# Kiến thức phân tích — blueprint giao dịch crypto

Tổng hợp từ tài liệu thiết kế dự án (SMC/ICT, risk, Monte Carlo, prediction markets).

## 3 chủ đề cốt lõi

1. **Cấu trúc thị trường (Market Structure)**  
   - Xác định trend, BOS (Break of Structure), CHoCH (Change of Character)  
   - Không trade ngược HTF  

2. **Thanh khoản & thao túng**  
   - Stop hunt / liquidity sweep tại swing high/low  
   - Order book imbalance + depth mỏng → skip  

3. **Confluence**  
   - Structure + vùng (premium/discount) + momentum + MC edge  
   - Không vào lệnh 1 tín hiệu đơn lẻ  

## Quy trình vào lệnh (bot)

1. Quan sát multi-venue spot + depth  
2. SMC score (bull/bear/range)  
3. Monte Carlo 10k → p_up / p_down  
4. MiroFish blend consensus  
5. Edge vs 50% (spot) hoặc vs Polymarket yes price  
6. Risk gate: liquidity, conflict, daily loss, consecutive losses  
7. Half-Kelly × Bayesian size  
8. Optional AI critique  
9. Execute paper/live + notify  

## Risk

| Rule | Giá trị mặc định |
|------|------------------|
| Half-Kelly | bật |
| Daily loss cap | 2% |
| Consecutive losses halt | 5 |
| Edge threshold | 5% |
| Max position | 5% equity (live nên 2%) |

## Go-live

Paper ≥ 7 ngày → 200 trades mục tiêu → win-rate tự đo → live $100 → scale sau 50 live trades.
