<template>
  <div class="dashboard">
    <!-- 状态卡片 -->
    <div class="status-cards">
      <el-card class="status-card" shadow="hover">
        <template #header>
          <div class="card-header">
            <span>价格信息</span>
          </div>
        </template>
        <div class="price-info">
          <div class="price-item">
            <span class="label">基准价格</span>
            <span class="value">{{ formatPrice(status.base_price) }}</span>
          </div>
          <div class="price-item">
            <span class="label">当前价格</span>
            <span class="value" :class="priceChangeClass">
              {{ formatPrice(status.current_price) }}
            </span>
          </div>
        </div>
      </el-card>

      <el-card class="status-card" shadow="hover">
        <template #header>
          <div class="card-header">
            <span>资金状况</span>
          </div>
        </template>
        <div class="trade-params">
          <div class="param-item">
            <span class="label">总资产</span>
            <span class="value">{{ formatPrice(status.total_assets) }}</span>
          </div>
          <div class="param-item">
            <span class="label">仓位比例</span>
            <span class="value">{{ formatPercent(status.position_ratio) }}</span>
          </div>
        </div>
      </el-card>
    </div>

    <!-- 交易历史 -->
    <el-card class="trade-history" shadow="hover">
      <template #header>
        <div class="card-header">
          <span>最近交易</span>
        </div>
      </template>
      <el-table :data="trades" style="width: 100%">
        <el-table-column prop="timestamp" label="时间" width="180">
          <template #default="scope">
            {{ formatTime(scope.row.timestamp) }}
          </template>
        </el-table-column>
        <el-table-column prop="side" label="方向" width="100">
          <template #default="scope">
            <el-tag :type="scope.row.side === 'buy' ? 'success' : 'danger'">
              {{ scope.row.side === 'buy' ? '买入' : '卖出' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="price" label="价格" width="120" />
        <el-table-column prop="amount" label="数量" width="120" />
        <el-table-column prop="profit" label="收益">
          <template #default="scope">
            <span :class="scope.row.profit >= 0 ? 'profit' : 'loss'">
              {{ formatProfit(scope.row.profit) }}
            </span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.dashboard {
  padding: 20px;
  background: #f5f7fa;
  min-height: 100vh;
}

.status-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 20px;
  margin-bottom: 20px;
}

.status-card {
  background: white;
  border-radius: 8px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.price-info, .trade-params {
  display: grid;
  gap: 15px;
}

.price-item, .param-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.profit { color: #67C23A; }
.loss { color: #F56C6C; }

.label {
  color: #909399;
  font-size: 14px;
}

.value {
  font-size: 16px;
  font-weight: 500;
}
</style> 