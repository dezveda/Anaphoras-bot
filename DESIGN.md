# DESIGN.md - Diseño Detallado de Módulos del Bot

Este documento describe el diseño detallado de cada módulo del bot de trading algorítmico.

## 1. Módulo de Conexión API (`BinanceConnector`)

*   **Responsabilidad Principal**: Gestionar toda la comunicación con la API de Binance Futuros (REST y WebSockets). Esto incluye autenticación, envío de solicitudes, manejo de respuestas, y gestión de errores de conexión y API.
*   **Clases Principales**:
    *   `BinanceAPI`: Clase central para interactuar con la API.
*   **Métodos Clave**:
    *   `__init__(api_key, api_secret, testnet=False)`
    *   `get_server_time()`: Verifica la conectividad y obtiene la hora del servidor.
    *   `get_exchange_info()`: Obtiene información de los pares, límites, etc.
    *   `get_klines(symbol, interval, startTime=None, endTime=None, limit=500)`: Obtiene datos de velas.
    *   `get_order_book(symbol, limit=100)`: Obtiene el libro de órdenes.
    *   `get_recent_trades(symbol, limit=500)`: Obtiene trades recientes.
    *   `get_mark_price(symbol=None)`: Obtiene el mark price.
    *   `get_funding_rate_history(symbol=None, startTime=None, endTime=None, limit=100)`: Obtiene historial de funding rates.
    *   `place_order(symbol, side, type, quantity, price=None, timeInForce=None, newClientOrderId=None, stopPrice=None, closePosition=None, workingType=None, reduceOnly=False)`: Coloca una nueva orden.
    *   `cancel_order(symbol, orderId=None, origClientOrderId=None)`: Cancela una orden.
    *   `get_order_status(symbol, orderId=None, origClientOrderId=None)`: Consulta el estado de una orden.
    *   `get_open_orders(symbol=None)`: Obtiene órdenes abiertas.
    *   `get_all_orders(symbol, orderId=None, startTime=None, endTime=None, limit=500)`: Obtiene todas las órdenes (historial).
    *   `get_account_balance()`: Obtiene el balance de la cuenta de futuros.
    *   `get_position_information(symbol=None)`: Obtiene información de las posiciones.
    *   `start_websocket_market_stream(streams, callback)`: Inicia un stream de mercado WebSocket.
    *   `stop_websocket_market_stream(stream_id)`: Detiene un stream de mercado.
    *   `start_user_data_stream(callback)`: Inicia el stream de datos de usuario.
    *   `keep_alive_user_data_stream()`: Mantiene vivo el listen key del user data stream.
    *   `close_user_data_stream()`: Cierra el stream de datos de usuario.
*   **Atributos Importantes**:
    *   `api_key`, `api_secret`
    *   `base_url_rest`, `base_url_ws`
    *   `session` (para `requests.Session`)
    *   `active_ws_connections` (diccionario para gestionar WebSockets activos)
*   **Interacciones**:
    *   Utilizado por `DataFetcher`, `OrderExecutor`, `Backtester` (para datos históricos).

## 2. Módulo de Adquisición de Datos (`DataFetcher`)

*   **Responsabilidad Principal**: Obtener, procesar y distribuir datos de mercado en tiempo real y datos históricos. Se suscribe a los streams de WebSocket necesarios y proporciona una interfaz unificada para que otros módulos accedan a los datos.
*   **Clases Principales**:
    *   `MarketDataProvider`: Gestiona la suscripción y distribución de datos.
*   **Métodos Clave**:
    *   `__init__(binance_connector)`
    *   `subscribe_to_kline_stream(symbol, interval, callback)`
    *   `subscribe_to_depth_stream(symbol, callback)`
    *   `subscribe_to_trade_stream(symbol, callback)`
    *   `subscribe_to_mark_price_stream(symbol, callback)`
    *   `get_latest_kline(symbol, interval)`: Devuelve la vela más reciente.
    *   `get_current_order_book(symbol)`: Devuelve el order book actual.
    *   `get_historical_klines(symbol, interval, start_str, end_str=None)`: Obtiene velas históricas.
*   **Atributos Importantes**:
    *   `binance_connector` (instancia de `BinanceConnector`)
    *   `live_data_handlers` (callbacks para diferentes tipos de datos)
    *   `current_klines`, `current_order_books` (almacenamiento interno de datos recientes)
*   **Interacciones**:
    *   Usa `BinanceConnector` para obtener datos.
    *   Proporciona datos a `StrategyEngine`, `GuiManager`.

## 3. Módulo de Estrategias de Trading (`StrategyEngine`)

*   **Responsabilidad Principal**: Contener, ejecutar y gestionar la lógica de las diferentes estrategias de trading. Recibe datos de mercado y genera señales de trading.
*   **Clases Principales**:
    *   `StrategyEngine`: Orquesta las estrategias.
    *   `BaseStrategy` (clase abstracta): Define la interfaz para todas las estrategias.
    *   Clases específicas para cada estrategia (ej. `DCAStrategy`, `FibonacciStrategy`, `HedgingStrategy`).
*   **Métodos Clave (`StrategyEngine`)**:
    *   `__init__(data_fetcher, order_executor, risk_manager)`
    *   `load_strategy(strategy_instance)`
    *   `run_strategies(market_data)`: Itera sobre las estrategias activas y las ejecuta.
    *   `on_market_data(data_type, data)`: Método llamado por `DataFetcher` para pasar nuevos datos.
*   **Métodos Clave (`BaseStrategy`)**:
    *   `__init__(params)`
    *   `process_data(data)`: Lógica principal de la estrategia.
    *   `generate_signals()`: Genera señales de compra/venta.
*   **Atributos Importantes (`StrategyEngine`)**:
    *   `active_strategies`
    *   `data_fetcher`, `order_executor`, `risk_manager`
*   **Interacciones**:
    *   Recibe datos de `DataFetcher`.
    *   Envía señales/órdenes a `OrderExecutor`.
    *   Consulta a `RiskManager` antes de operar.

## 4. Módulo de Ejecución de Órdenes (`OrderExecutor`)

*   **Responsabilidad Principal**: Gestionar la colocación, modificación y cancelación de órdenes en Binance. Traduce las señales de trading en órdenes reales o simuladas (para backtesting). Gestiona el ciclo de vida de las órdenes.
*   **Clases Principales**:
    *   `OrderManager`: Encargado de la ejecución y seguimiento.
*   **Métodos Clave**:
    *   `__init__(binance_connector, risk_manager)`
    *   `execute_signal(signal_event)`: Procesa una señal de `StrategyEngine`.
    *   `place_new_order(symbol, side, type, quantity, price=None, ...)`
    *   `cancel_existing_order(symbol, order_id)`
    *   `update_order_status(order_update_data)`: Actualiza el estado de una orden (desde User Data Stream).
    *   `get_open_positions(symbol=None)`
*   **Atributos Importantes**:
    *   `binance_connector`, `risk_manager`
    *   `active_orders`, `filled_orders`, `cancelled_orders`
*   **Interacciones**:
    *   Recibe señales de `StrategyEngine`.
    *   Usa `BinanceConnector` para interactuar con la API de Binance.
    *   Consulta a `RiskManager` para validación de órdenes.
    *   Recibe actualizaciones de User Data Stream a través de `BinanceConnector` o un manejador dedicado.

## 5. Módulo de Backtesting (`Backtester`)

*   **Responsabilidad Principal**: Simular la ejecución de estrategias de trading con datos históricos para evaluar su rendimiento.
*   **Clases Principales**:
    *   `BacktestEngine`: Ejecuta el backtest.
*   **Métodos Clave**:
    *   `__init__(data_fetcher, strategy_engine_config, initial_capital)`
    *   `load_historical_data(symbol, interval, start_date, end_date)`
    *   `run_backtest()`
    *   `generate_performance_report()`: Calcula métricas (P&L, drawdown, Sharpe, etc.).
    *   `simulate_order_execution(order_params)`
*   **Atributos Importantes**:
    *   `historical_data`
    *   `simulated_trades`, `equity_curve`
    *   `performance_metrics`
*   **Interacciones**:
    *   Usa `DataFetcher` para obtener datos históricos.
    *   Simula el `StrategyEngine` y el `OrderExecutor`.

## 6. Módulo de Gestión de Riesgos (`RiskManager`)

*   **Responsabilidad Principal**: Implementar lógicas para controlar el riesgo, como el tamaño de la posición, niveles de stop-loss, y límites de pérdida.
*   **Clases Principales**:
    *   `RiskRules`: Define y evalúa las reglas de riesgo.
*   **Métodos Clave**:
    *   `__init__(account_balance_provider_or_initial_capital)`
    *   `calculate_position_size(symbol, entry_price, stop_loss_price, risk_per_trade_percentage)`
    *   `check_order_validity(order_params)`: Valida una orden propuesta contra las reglas de riesgo.
    *   `should_apply_stop_loss(current_price, position_data)`
    *   `should_apply_take_profit(current_price, position_data)`
*   **Atributos Importantes**:
    *   `max_risk_per_trade`, `max_drawdown_limit`
    *   `current_account_balance`
*   **Interacciones**:
    *   Consultado por `StrategyEngine` y `OrderExecutor`.

## 7. Módulo de Logging (`Logger`)

*   **Responsabilidad Principal**: Registrar todas las operaciones, decisiones, errores y métricas de rendimiento del bot en archivos de log.
*   **Clases Principales**:
    *   (Puede usar la biblioteca `logging` estándar de Python, configurada adecuadamente).
*   **Métodos Clave (Configuración)**:
    *   `setup_logger(log_level, log_file_path)`
*   **Interacciones**:
    *   Utilizado por todos los demás módulos para registrar información.

## 8. Módulo de Interfaz de Usuario (`GuiManager`)

*   **Responsabilidad Principal**: Gestionar la interfaz gráfica de usuario (GUI). Mostrar datos, permitir configuración y control del bot.
*   **Clases Principales** (dependerá de PySide6):
    *   `MainWindow` (Ventana principal)
    *   Vistas específicas (ej. `DashboardView`, `SettingsView`, `TradesView`, `BacktestView`)
    *   Controladores o Lógica de UI para conectar la UI con el backend.
*   **Métodos Clave**:
    *   `__init__(data_fetcher, strategy_engine, order_executor, backtester_engine)`
    *   `start_gui()`
    *   `update_market_data_display(data)`
    *   `update_pnl_display(pnl_info)`
    *   `update_order_display(order_info)`
    *   `handle_user_config_changes()`
    *   `run_backtest_from_gui(params)`
*   **Atributos Importantes**:
    *   Referencias a los módulos del backend.
    *   Estado de la UI.
*   **Interacciones**:
    *   Recibe datos de `DataFetcher`, `OrderExecutor`, `StrategyEngine` (estado), `Backtester`.
    *   Envía comandos/configuraciones a los módulos del backend.

## 9. (Opcional) Módulo de Comunicación IA (`AICommunicator`)

*   **Responsabilidad Principal**: Facilitar el intercambio de información con la IA de Windsurf mediante la lectura/escritura de un archivo específico.
*   **Clases Principales**:
    *   `FileInterface`: Lee y escribe en el archivo de comunicación.
*   **Métodos Clave**:
    *   `__init__(file_path, format='json')`
    *   `write_data_to_file(data_to_write)`
    *   `read_data_from_file()`
    *   `check_for_updates()`: Verifica si el archivo ha sido modificado.
*   **Atributos Importantes**:
    *   `file_path`, `file_format`
    *   `last_modified_timestamp`
*   **Interacciones**:
    *   Puede ser consultado por `StrategyEngine` para obtener señales/parámetros externos.
    *   Puede ser llamado por `StrategyEngine` o `Logger` para escribir información relevante para la IA.

---
Este es un esqueleto inicial. Cada sección necesitará más detalles a medida que avance el diseño específico de cada funcionalidad.

## 10. Diseño Detallado de Estrategias de Trading

Esta sección detalla la lógica, parámetros clave, y condiciones de entrada/salida para las estrategias de trading implementadas en el `StrategyEngine`.

### 10.1 Estrategia de DCA Avanzado (`AdvancedDCAStrategy`)

*   **Concepto**: Realizar compras (o ventas en corto) escalonadas a medida que el precio se mueve en contra de la posición inicial, promediando el precio de entrada y buscando una salida rentable en un retroceso. "Avanzado" puede implicar factores dinámicos para los niveles de entrada o el tamaño de las órdenes.
*   **Lógica Principal**:
    1.  **Entrada Inicial**: Se abre una posición inicial (Larga o Corta) basada en una señal primaria (que puede provenir de otra estrategia o un análisis manual/externo).
    2.  **Definición de Órdenes de Seguridad (Safety Orders - SO)**:
        *   Se predefinen múltiples niveles de precios por debajo (para Largos) o por encima (para Cortos) de la entrada inicial donde se colocarán órdenes de seguridad.
        *   Cada SO tendrá un tamaño específico, que puede aumentar progresivamente (ej. 1x, 1.5x, 2x el tamaño de la orden base).
    3.  **Ejecución de SO**: Si el precio alcanza un nivel de SO, la orden se ejecuta, aumentando el tamaño de la posición y promediando el precio de entrada.
    4.  **Cálculo de Take Profit (TP)**: El objetivo de TP se recalcula después de cada SO. Se basa en un porcentaje deseado de ganancia sobre el precio promedio ponderado de la posición total.
    5.  **Salida**: La posición se cierra cuando se alcanza el precio de TP.
*   **Parámetros Clave**:
    *   `initial_order_type`: (LONG, SHORT) - Define la dirección de la estrategia.
    *   `base_order_size`: (decimal) - Tamaño de la orden inicial.
    *   `safety_order_size_multiplier`: (list of decimals, e.g., [1.0, 1.5, 2.0]) - Multiplicador para el tamaño de cada SO respecto al `base_order_size`.
    *   `price_deviation_for_so`: (list of percentages, e.g., [1.0, 2.5, 4.5]) - Desviación de precio (en %) desde la última entrada para colocar la siguiente SO.
    *   `max_safety_orders`: (integer) - Número máximo de SOs a colocar.
    *   `take_profit_percentage`: (decimal) - Porcentaje de ganancia deseado sobre el precio promedio.
    *   `signal_source`: (string/object, opcional) - Fuente de la señal de entrada inicial.
*   **Condiciones de Entrada**:
    *   Señal de `signal_source` (si se define) O activación manual/externa.
*   **Condiciones de Salida**:
    *   Precio alcanza el `take_profit_percentage` calculado sobre el precio promedio de la posición.
    *   (Opcional) Un stop-loss global para la estrategia si el precio se mueve demasiado en contra después de todas las SO.
*   **Mejoras "Avanzadas" a Considerar**:
    *   Ajuste dinámico de `price_deviation_for_so` basado en la volatilidad actual (ej. usando ATR).
    *   Ajuste dinámico de `safety_order_size_multiplier` basado en la confianza de la señal o el nivel de SO.
    *   Trailing take profit.

### 10.2 Estrategia de Cobertura (Hedging) (`HedgingStrategy`)

*   **Concepto**: Abrir una posición en la dirección opuesta a una posición principal existente para mitigar pérdidas potenciales durante movimientos adversos del mercado, sin cerrar la posición original.
*   **Lógica Principal**:
    1.  **Posición Principal**: Se asume que existe una posición principal (Larga o Corta) abierta (manejada por esta u otra estrategia).
    2.  **Condición de Activación de Cobertura**: Se define una condición que dispara la cobertura (ej. el precio cae un X% por debajo de la entrada de un Largo, o un indicador específico sugiere un retroceso temporal).
    3.  **Apertura de Posición de Cobertura**: Se abre una orden en la dirección opuesta (ej. Corto para cubrir un Largo).
        *   El tamaño de la cobertura puede ser una fracción o el total de la posición principal.
    4.  **Condición de Cierre de Cobertura**: Se define una condición para cerrar la posición de cobertura (ej. el precio se recupera a un cierto nivel, la condición de retroceso original desaparece).
    5.  **Gestión**: La posición principal permanece abierta. El objetivo es que la ganancia de la cobertura compense (parcial o totalmente) la pérdida no realizada de la posición principal durante el retroceso.
*   **Parámetros Clave**:
    *   `primary_position_symbol`: (string) - Símbolo de la posición a cubrir.
    *   `hedge_trigger_percentage_drop` (para Largos) / `hedge_trigger_percentage_rise` (para Cortos): (decimal) - Caída/subida porcentual desde el precio de entrada de la posición principal para activar la cobertura.
    *   `hedge_ratio`: (decimal, e.g., 0.5, 1.0) - Proporción del tamaño de la posición principal a cubrir. 1.0 significa cobertura total.
    *   `close_hedge_percentage_recovery` (para Largos) / `close_hedge_percentage_retrace` (para Cortos): (decimal) - Porcentaje de recuperación/retroceso desde el punto más bajo/alto del movimiento adverso para cerrar la cobertura.
    *   `max_hedge_duration`: (integer, opcional) - Tiempo máximo para mantener la cobertura abierta.
    *   (Alternativa a triggers porcentuales): `indicator_based_trigger`: (configuración de indicador) - Usar un indicador técnico (ej. cruce de MA, RSI en sobrecompra/venta) para activar/desactivar la cobertura.
*   **Condiciones de Entrada (Apertura de Cobertura)**:
    *   Precio alcanza `hedge_trigger_percentage_drop/rise` respecto a la posición principal.
    *   O, señal de `indicator_based_trigger`.
*   **Condiciones de Salida (Cierre de Cobertura)**:
    *   Precio alcanza `close_hedge_percentage_recovery/retrace`.
    *   O, señal de `indicator_based_trigger` se revierte.
    *   O, `max_hedge_duration` alcanzado.
*   **Consideraciones**:
    *   Requiere un seguimiento cuidadoso de la posición principal.
    *   Las comisiones de las operaciones de cobertura deben ser consideradas.
    *   El "costo" de la cobertura es que si el mercado se revierte rápidamente a favor de la posición principal después de abrir la cobertura, las ganancias de la posición principal se ven reducidas por las pérdidas de la cobertura.

### 10.3 Estrategia de Fibonacci Circular en Cascada/Círculos Concéntricos (`CircularFibonacciStrategy`)

*   **Concepto**: Esta es una técnica no estándar y visualmente orientada. Se basa en la idea de dibujar círculos (o arcos) basados en niveles de Fibonacci proyectados desde un punto pivote significativo (un máximo o mínimo importante) en el gráfico de precios. Las "cascadas" o "círculos concéntricos" actuarían como niveles dinámicos de soporte/resistencia o puntos de inflexión temporal.
*   **Lógica Conceptual (Interpretación)**:
    1.  **Identificación del Pivote Central (P0)**: Se identifica un punto de pivote mayor significativo en el historial de precios (ej. un máximo o mínimo importante reciente en una temporalidad relevante). Este será el centro de los círculos.
    2.  **Identificación de un Pivote Secundario (P1) o Radio Base**: Se necesita un segundo punto o un método para definir el radio del primer círculo (o el "paso" entre círculos).
        *   Esto podría ser otro pivote menor que define un radio inicial.
        *   O, podría ser una distancia de precio (ej. basada en ATR desde P0, o un porcentaje del precio en P0).
        *   O, podría ser un tiempo (número de barras) hasta un evento significativo.
    3.  **Proyección de Círculos de Fibonacci**:
        *   Desde P0, usando el radio base (distancia P0-P1 o el radio calculado), se proyectan círculos (o arcos si solo se considera el futuro) cuyos radios son múltiplos de Fibonacci del radio base (ej. 0.618R, 1.0R, 1.618R, 2.618R, etc.). Estos son los círculos concéntricos.
        *   "En cascada" podría implicar que una vez que el precio interactúa significativamente con un círculo, ese punto de interacción podría convertirse en un nuevo P0 para una nueva serie de círculos, o ajustar el radio de los círculos existentes.
    4.  **Interpretación de los Círculos**:
        *   Los perímetros de estos círculos se observan como posibles niveles dinámicos de soporte/resistencia.
        *   La interacción del precio con estos círculos (toques, cruces, rechazos) podría generar señales.
        *   La "distancia" del precio actual al próximo perímetro de círculo podría indicar cuán cerca está de un posible punto de reacción.
        *   El tiempo también juega un papel: los círculos se expanden con el tiempo si el radio está vinculado al tiempo, o el precio los alcanza en diferentes momentos.
*   **Parámetros Clave (Propuestos)**:
    *   `central_pivot_lookback`: (integer) - Cuántas barras mirar hacia atrás para identificar P0 (ej. buscando el máximo más alto o mínimo más bajo).
    *   `radius_definition_method`: ('pivot_to_pivot', 'atr_multiplier', 'price_percentage', 'fixed_value')
    *   `radius_atr_period` (si `atr_multiplier`): (integer)
    *   `radius_atr_multiplier` (si `atr_multiplier`): (decimal)
    *   `radius_price_percentage` (si `price_percentage`): (decimal)
    *   `secondary_pivot_lookback` (si `pivot_to_pivot`): (integer)
    *   `fib_levels_for_radii`: (list of decimals, e.g., [0.618, 1.0, 1.618, 2.618]) - Niveles de Fibonacci para escalar el radio base.
    *   `cascade_trigger_condition`: (string, opcional) - Condición para re-calcular P0 o radios (ej. "strong_breakout_of_circle_X").
    *   `signal_on_touch`: (boolean) - Generar señal al tocar un círculo.
    *   `signal_on_cross_and_retest`: (boolean) - Generar señal si cruza y luego retestea el círculo como S/R.
*   **Condiciones de Entrada/Salida (Muy Especulativas)**:
    *   **Entrada**:
        *   Comprar si el precio toca y es rechazado desde abajo por el perímetro de un círculo de Fibonacci (actuando como soporte).
        *   Vender si el precio toca y es rechazado desde arriba por el perímetro de un círculo de Fibonacci (actuando como resistencia).
        *   Comprar en un breakout alcista confirmado por encima de un círculo importante.
        *   Vender en un breakdown bajista confirmado por debajo de un círculo importante.
    *   **Salida (Stop Loss/Take Profit)**:
        *   Stop loss podría ser al otro lado del círculo de Fibonacci que se está probando, o basado en un ATR.
        *   Take profit podría ser el siguiente nivel de círculo de Fibonacci en la dirección del trade, o un ratio R:R.
*   **Desafíos y Consideraciones**:
    *   **Subjetividad**: La elección de P0 y P1 (o el método del radio base) puede ser subjetiva y afectar drásticamente los círculos.
    *   **Complejidad de Implementación Visual y Algorítmica**: Representar y calcular esto algorítmicamente para la toma de decisiones automatizada es complejo. La descripción original menciona "uso y aplicación", lo que implica que debe ser más que una herramienta de dibujo manual.
    *   **Backtesting**: Difícil de backtestear de manera robusta debido a su naturaleza dinámica y potencialmente dependiente de la interpretación.
    *   **"Cascada"**: La lógica de "cascada" (cómo y cuándo se actualizan los círculos) necesita una definición muy precisa.
    *   Para una implementación automatizada, se necesitarían reglas muy claras sobre cómo se identifican P0 y P1, y cómo se interpretan las interacciones con los círculos para generar señales discretas.

### 10.4 Estrategia de Puntos Pivote (`PivotPointStrategy`)

*   **Concepto**: Utilizar los puntos pivote clásicos (calculados a partir del Alto, Bajo y Cierre del período anterior) y sus niveles de soporte (S1, S2, S3) y resistencia (R1, R2, R3) como zonas clave para tomar decisiones de trading.
*   **Lógica Principal**:
    1.  **Cálculo de Puntos Pivote**:
        *   Al inicio de cada nuevo período (ej. diario, semanal), calcular el Punto Pivote (PP), Soportes (S1, S2, S3) y Resistencias (R1, R2, R3).
        *   Fórmula Clásica:
            *   PP = (Alto_prev + Bajo_prev + Cierre_prev) / 3
            *   S1 = (2 * PP) - Alto_prev
            *   R1 = (2 * PP) - Bajo_prev
            *   S2 = PP - (Alto_prev - Bajo_prev)
            *   R2 = PP + (Alto_prev - Bajo_prev)
            *   S3 = Bajo_prev - 2 * (Alto_prev - PP)
            *   R3 = Alto_prev + 2 * (PP - Bajo_prev)
        *   Existen otras variantes (Woodie, Camarilla, Fibonacci Pivots) que podrían considerarse como extensiones.
    2.  **Generación de Señales**:
        *   **Rebotes**:
            *   Buscar compras cuando el precio testea y es rechazado desde un nivel de soporte (S1, S2, S3) o el PP (si está por debajo del precio de apertura).
            *   Buscar ventas cuando el precio testea y es rechazado desde un nivel de resistencia (R1, R2, R3) o el PP (si está por encima del precio de apertura).
        *   **Rupturas (Breakouts)**:
            *   Buscar compras si el precio rompe decisivamente por encima de un nivel de resistencia (R1, R2, R3).
            *   Buscar ventas si el precio rompe decisivamente por debajo de un nivel de soporte (S1, S2, S3).
    3.  **Confirmación**: Las señales pueden requerir confirmación de otros indicadores (ej. volumen, RSI, patrones de velas).
*   **Parámetros Clave**:
    *   `pivot_period`: ('daily', 'weekly', 'monthly') - Período para el cálculo de los pivotes.
    *   `pivot_formula`: ('classic', 'woodie', 'camarilla', 'fibonacci') - Tipo de fórmula de pivote.
    *   `trade_type`: ('rebound', 'breakout', 'both') - Tipo de señal a operar.
    *   `confirmation_indicator`: (string, opcional) - Indicador adicional para confirmar señales.
    *   `stop_loss_factor`: (decimal) - Factor para ATR o distancia fija para SL.
    *   `take_profit_target`: ('next_pivot', 'fixed_rr', 'percentage') - Cómo calcular el TP.
*   **Condiciones de Entrada**:
    *   **Rebote Alcista**: Precio toca S1/S2/S3 o PP (como soporte) y muestra signos de reversión (ej. vela alcista, divergencia RSI).
    *   **Rebote Bajista**: Precio toca R1/R2/R3 o PP (como resistencia) y muestra signos de reversión.
    *   **Ruptura Alcista**: Cierre de vela confirmado por encima de R1/R2/R3 con aumento de volumen.
    *   **Ruptura Bajista**: Cierre de vela confirmado por debajo de S1/S2/S3 con aumento de volumen.
*   **Condiciones de Salida**:
    *   **Stop Loss**: Por debajo del nivel de soporte (para largos) o por encima del nivel de resistencia (para cortos), o basado en ATR/distancia fija.
    *   **Take Profit**:
        *   Siguiente nivel de pivote en la dirección del trade.
        *   Ratio Riesgo/Recompensa fijo (ej. 1:1.5, 1:2).
        *   Porcentaje fijo.
*   **Consideraciones**:
    *   Los niveles de pivote son más significativos en mercados laterales o cuando el precio se acerca a ellos por primera vez después de su cálculo.
    *   En mercados con fuerte tendencia, las rupturas pueden ser más fiables que los rebotes.

### 10.5 Estrategia de Puntos de Liquidez (`LiquidityPointsStrategy`)

*   **Concepto**: Identificar niveles de precios donde se espera que exista una alta concentración de órdenes (liquidez), como zonas de stop-loss agrupados o niveles de precios psicológicos. El bot intentará operar anticipando que el precio será atraído hacia estos puntos o reaccionará fuertemente al alcanzarlos.
*   **Lógica Principal (Interpretativa, ya que la identificación precisa es compleja)**:
    1.  **Identificación de Zonas de Liquidez Potencial**:
        *   **Máximos y Mínimos Anteriores (Swing Highs/Lows)**: Se asume que hay stops por encima de máximos recientes y por debajo de mínimos recientes.
        *   **Niveles de Precios Redondos/Psicológicos**: (ej. $30,000, $35,000 para BTC).
        *   **Niveles de Alta Concentración de Volumen (Volume Profile)**: Zonas donde históricamente se ha negociado mucho volumen (HVN - High Volume Nodes). El Point of Control (POC) es especialmente relevante.
        *   **Order Book Imbalance (Limitado por API)**: Grandes desequilibrios entre órdenes de compra y venta en el libro de órdenes pueden indicar zonas de liquidez o "muros". Sin embargo, el acceso a profundidad completa del order book y su análisis en tiempo real es intensivo.
        *   **Niveles de Liquidación (Estimados)**: Basado en posiciones abiertas y apalancamiento (información no directamente disponible de forma pública y precisa para todo el mercado).
    2.  **Generación de Señales (Heurísticas)**:
        *   **"Stop Run" o "Liquidity Grab"**:
            *   Si el precio se acerca a un máximo/mínimo reciente y luego lo supera ligeramente para luego revertir rápidamente, se puede operar en la dirección de la reversión (asumiendo que se barrieron los stops).
        *   **Atracción a HVN/POC**:
            *   Si el precio está lejos de un HVN/POC significativo, se puede esperar que sea atraído hacia él. Operar en esa dirección si otros factores lo apoyan.
        *   **Reacción en HVN/POC**:
            *   Operar rebotes o rupturas desde HVNs/POC, similar a los niveles S/R.
        *   **Anticipación de Movimiento a Niveles Redondos**: Operar hacia un nivel redondo si el precio se aproxima con momentum.
*   **Parámetros Clave**:
    *   `liquidity_source_types`: (list: ['swing_points', 'round_numbers', 'volume_profile', 'order_book_imbalance']) - Qué tipos de fuentes de liquidez considerar.
    *   `swing_point_lookback`: (integer) - Período para identificar swing highs/lows.
    *   `volume_profile_period`: (integer) - Período para calcular el perfil de volumen.
    *   `round_number_sensitivity`: (integer) - Ej. cada $500, $1000.
    *   `order_book_depth_levels` (si se usa): (integer) - Cuántos niveles del libro analizar.
    *   `order_book_imbalance_ratio`: (decimal) - Ratio para considerar un desequilibrio significativo.
    *   `atr_filter_for_reaction_zone`: (decimal) - Factor ATR para definir una "zona" alrededor del punto de liquidez.
*   **Condiciones de Entrada/Salida (Ejemplos)**:
    *   **Entrada (Stop Run - Largo)**: Precio rompe por debajo de un mínimo reciente, pero la siguiente vela cierra fuertemente alcista por encima del mínimo.
    *   **Entrada (Atracción a POC - Largo)**: Precio está por debajo del POC diario, y un indicador de momentum muestra fuerza alcista.
    *   **Salida**:
        *   Stop loss basado en ATR o invalidación de la configuración (ej. si en un "stop run" el precio continúa en la dirección de la ruptura).
        *   Take profit en un nivel de S/R opuesto, o un ratio R:R.
*   **Desafíos**:
    *   La liquidez es dinámica y difícil de predecir con certeza.
    *   El "Order Book Imbalance" puede ser manipulado (spoofing).
    *   Requiere una interpretación sofisticada de la acción del precio y el volumen.
    *   La información sobre liquidaciones a nivel de mercado no es fácilmente accesible para un bot minorista.

### 10.6 Estrategia de Adaptación a Tendencias (`TrendAdaptationStrategy`)

*   **Concepto**: Identificar la tendencia predominante del mercado (alcista, bajista, lateral) en diferentes temporalidades (macro y micro) y ajustar dinámicamente los parámetros de otras estrategias operativas o seleccionar diferentes estrategias secundarias que funcionen mejor en el régimen de mercado actual. Con especial enfoque en operar a favor de las macrotendencias.
*   **Lógica Principal**:
    1.  **Identificación de Tendencia (Multi-Temporalidad)**:
        *   **Macrotendencia**: Usar indicadores en temporalidades altas (ej. Diario, Semanal) como Medias Móviles (ej. SMA 50, SMA 200), ADX, o análisis de estructura de mercado (altos más altos, bajos más altos).
        *   **Microtendencia/Condición Actual**: Usar indicadores en temporalidades operativas (ej. 1H, 4H) como EMA cortas, RSI, MACD.
    2.  **Definición de Regímenes de Mercado**:
        *   Macrotendencia Alcista, Microtendencia Alcista.
        *   Macrotendencia Alcista, Microtendencia Correctiva/Lateral.
        *   Macrotendencia Bajista, Microtendencia Bajista.
        *   Macrotendencia Bajista, Microtendencia Correctiva/Lateral.
        *   Mercado Lateral (sin macrotendencia clara).
    3.  **Adaptación de Estrategias**:
        *   **Selección de Estrategia**: Activar/desactivar estrategias secundarias. Ej:
            *   En Macrotendencia Alcista: Favorecer estrategias de compra en retrocesos, breakouts alcistas.
            *   En Macrotendencia Bajista: Favorecer estrategias de venta en rallies, breakouts bajistas.
            *   En Mercado Lateral: Favorecer estrategias de reversión a la media, rangos, pivotes.
        *   **Ajuste de Parámetros**: Modificar parámetros de las estrategias activas. Ej:
            *   Aumentar tamaño de posición o TP en trades a favor de la macrotendencia.
            *   Reducir tamaño de posición o usar SL más ajustados en trades contra la macrotendencia (o evitarlos).
            *   Ajustar la sensibilidad de los indicadores (periodos más largos en mercados tendenciales, más cortos en laterales).
*   **Parámetros Clave**:
    *   `macro_trend_indicators`: (list of dicts: [{'name': 'SMA', 'period': 200, 'timeframe': '1D'}, ...])
    *   `micro_trend_indicators`: (list of dicts: [{'name': 'EMA', 'period': 20, 'timeframe': '1H'}, ...])
    *   `regime_definitions`: (ruleset) - Cómo se define cada régimen basado en los indicadores.
    *   `strategy_adaptations_per_regime`: (dict) - Mapeo de regímenes a acciones (activar/desactivar estrategia X, cambiar parámetro Y de estrategia Z).
*   **Funcionamiento**:
    *   Este módulo actuaría como un "director" o "estado" para el `StrategyEngine`.
    *   Periódicamente (o en cada nueva vela de la temporalidad de análisis), reevalúa la tendencia y el régimen.
    *   Aplica los cambios de configuración a las estrategias gestionadas por `StrategyEngine`.
*   **Consideraciones**:
    *   La definición precisa de los regímenes y las adaptaciones es crucial y compleja.
    *   Evitar la sobre-optimización al definir las reglas de adaptación.
    *   El enfoque principal es "aprovechar las macrotendencias", por lo que las señales de la macrotendencia deberían tener un peso mayor.

### 10.7 Estrategia Basada en Heurísticas de Indicadores (`IndicatorHeuristicStrategy`)

*   **Concepto**: Esta no es una estrategia única, sino un marco para crear señales de trading basadas en la combinación y la interpretación heurística de múltiples indicadores técnicos y subindicadores. El objetivo es desarrollar una "utilidad o provecho heurístico" de este monitoreo.
*   **Lógica Principal**:
    1.  **Selección de Indicadores**: Se elige un conjunto de indicadores relevantes (ej. RSI, MACD, Estocástico, Bandas de Bollinger, Volumen, Medias Móviles, ADX, Ichimoku, etc.).
    2.  **Definición de Condiciones por Indicador**: Para cada indicador, se definen condiciones específicas (ej. RSI > 70 para sobrecompra, cruce de MACD, precio tocando Banda de Bollinger inferior).
    3.  **Combinación Heurística (Sistema de Puntuación o Reglas Complejas)**:
        *   Se crea una lógica que combina las condiciones de múltiples indicadores para generar una señal final.
        *   **Sistema de Puntuación**: A cada condición cumplida se le asigna un puntaje (positivo para alcista, negativo para bajista). Si el puntaje total supera un umbral, se genera una señal.
        *   **Reglas Lógicas Complejas**: Usar operadores AND/OR para combinar condiciones (ej. "SI RSI < 30 Y MACD cruza hacia arriba ENTONCES Comprar").
    4.  **Generación de Señales**: Se generan señales de COMPRA, VENTA o MANTENER basadas en la salida de la lógica heurística.
*   **Parámetros Clave**:
    *   `indicator_configs`: (list of dicts) - Cada dict define un indicador, sus parámetros (periodos, etc.) y las condiciones a monitorear.
        *   Ej: `{'name': 'RSI', 'period': 14, 'conditions': {'oversold': 30, 'overbought': 70}}`
        *   Ej: `{'name': 'MACD', 'fast': 12, 'slow': 26, 'signal': 9, 'conditions': ['bullish_cross', 'bearish_cross']}`
    *   `heuristic_logic`: (dict or custom script/rules engine) - Define cómo se combinan las condiciones.
        *   Si es sistema de puntuación: `{'type': 'scoring', 'conditions_scores': {'RSI_oversold': 2, 'MACD_bullish_cross': 3}, 'buy_threshold': 4, 'sell_threshold': -4}`
        *   Si es reglas: `{'type': 'rules', 'buy_rules': ["RSI_oversold AND MACD_bullish_cross"], 'sell_rules': ["RSI_overbought AND MACD_bearish_cross"]}`
    *   `default_stop_loss_pips_or_atr`: (decimal)
    *   `default_take_profit_pips_or_atr`: (decimal)
*   **Condiciones de Entrada/Salida**:
    *   Definidas por la `heuristic_logic` y los umbrales/reglas configurados.
*   **Implementación**:
    *   Cada "heurística" podría ser una sub-clase o una configuración específica de `IndicatorHeuristicStrategy`.
    *   El `StrategyEngine` podría cargar múltiples instancias de esta con diferentes configuraciones de indicadores y lógicas.
*   **Consideraciones**:
    *   Altamente personalizable y potente si se diseña bien.
    *   Riesgo de sobre-optimización si se ajustan demasiados indicadores y reglas a datos históricos específicos.
    *   Requiere una cuidadosa selección de indicadores que no sean redundantes y que ofrezcan información complementaria.
    *   La "utilidad o provecho heurístico" se desarrolla a través de la experimentación y el entendimiento de cómo interactúan los indicadores en diferentes condiciones de mercado.

## 11. Esbozo Detallado de la Interfaz de Usuario (GUI)

Esta sección describe la estructura y componentes de las principales vistas de la Interfaz de Usuario (GUI) del bot. La GUI se desarrollará utilizando PySide6.

### 11.1 Vista: Dashboard Principal

*   **Propósito**: Proporcionar una visión general del estado del bot, rendimiento y condiciones clave del mercado de un vistazo.
*   **Información Clave Mostrada**:
    *   Estado del Bot: (ej. "Conectado", "Operando", "Detenido", "Error", "Backtesting en curso").
    *   Conexión API Binance: (ej. "Conectado", "Desconectado").
    *   P&L Total (Realizado): Calculado desde el inicio de la sesión o un período configurable.
    *   P&L Abierto (No Realizado): De las posiciones actualmente abiertas.
    *   Balance de la Cuenta de Futuros (USDT o el colateral principal).
    *   Precio Actual BTC/USDT.
    *   Cambio de Precio BTC/USDT (últimas 24h).
    *   Volumen BTC/USDT (últimas 24h).
    *   Últimos Mensajes de Log Importantes (ej. errores, trades ejecutados).
*   **Elementos Interactivos**:
    *   Botón "Iniciar Bot" / "Detener Bot".
    *   Botón "Conectar a Binance" / "Desconectar de Binance".
    *   (Opcional) Un pequeño gráfico de la curva de equidad de la sesión actual.
*   **Esbozo General del Layout**:
    *   **Panel Superior**: Estado del Bot, Estado API, P&L Total, P&L Abierto, Balance.
    *   **Panel Izquierdo/Lateral**: Quizás navegación a otras vistas si no se usan pestañas.
    *   **Área Central**:
        *   Sección de Información de Mercado (Precio BTC, Cambio, Volumen).
        *   (Opcional) Gráfico de Equidad.
    *   **Panel Inferior**: Ventana con los últimos mensajes de log (scrollable).

### 11.2 Vista: Configuración del Bot y Estrategias

*   **Propósito**: Permitir al usuario configurar los parámetros generales del bot, las claves API, y los parámetros específicos para cada estrategia de trading.
*   **Información Clave Mostrada / Campos de Configuración**:
    *   **Configuración General del Bot**:
        *   Campos para API Key y Secret Key de Binance (con opción de ocultar/mostrar).
        *   Botón "Probar Conexión API".
        *   Checkbox "Usar Testnet".
        *   Capital asignado al bot (si se gestiona explícitamente).
        *   Nivel de Logging (DEBUG, INFO, WARNING, ERROR).
    *   **Configuración de Estrategias**:
        *   Lista de estrategias disponibles (ej. `AdvancedDCAStrategy`, `PivotPointStrategy`).
        *   Para cada estrategia en la lista:
            *   Checkbox "Habilitar/Deshabilitar Estrategia".
            *   Botón "Configurar Parámetros de Estrategia" (abriría un diálogo/sub-vista).
            *   **Sub-Vista de Parámetros de Estrategia (ej. para DCA)**:
                *   Campos para `base_order_size`, `safety_order_size_multiplier` (podría ser una tabla o lista editable), `price_deviation_for_so`, `max_safety_orders`, `take_profit_percentage`, etc.
                *   Validación de datos de entrada.
    *   **Configuración de Comunicación IA (Opcional)**:
        *   Ruta del archivo de comunicación.
        *   Frecuencia de lectura/escritura.
*   **Elementos Interactivos**:
    *   Campos de texto, checkboxes, botones ("Guardar Configuración", "Cargar Configuración", "Restaurar Predeterminados").
    *   Selectores de archivo (para ruta de log, archivo IA).
    *   Tablas editables o listas para parámetros de múltiples valores (ej. niveles de DCA).
*   **Esbozo General del Layout**:
    *   Podría usar un sistema de Pestañas o un TreeView a la izquierda para seleccionar la categoría de configuración (General, API, Estrategia X, Estrategia Y, IA).
    *   El área principal mostraría los campos de configuración para la categoría seleccionada.
    *   Botones "Guardar" y "Cancelar/Cerrar" en la parte inferior.

### 11.3 Vista: Visualización de Gráficos de Precios e Indicadores

*   **Propósito**: Mostrar gráficos de velas (candlesticks) del par BTC/USDT en diferentes temporalidades, con la capacidad de superponer indicadores técnicos.
*   **Información Clave Mostrada**:
    *   Gráfico de Velas (OHLCV) para BTC/USDT.
    *   Indicadores técnicos superpuestos (ej. Medias Móviles, Bandas de Bollinger).
    *   Indicadores en sub-paneles (ej. RSI, MACD, Volumen).
    *   Posiciones abiertas y órdenes pendientes marcadas en el gráfico.
*   **Elementos Interactivos**:
    *   Selector de Temporalidad (1m, 5m, 15m, 1H, 4H, 1D).
    *   Herramientas de dibujo básicas (líneas de tendencia, niveles S/R) - (Avanzado, podría ser post-MVP).
    *   Selector de Indicadores:
        *   Lista de indicadores disponibles.
        *   Opción para añadir/quitar indicadores del gráfico.
        *   Configuración de parámetros para cada indicador (ej. período de MA, niveles RSI).
    *   Zoom y desplazamiento (pan) en el gráfico.
    *   Botón para actualizar/recargar datos del gráfico.
*   **Esbozo General del Layout**:
    *   **Panel Superior/Barra de Herramientas**: Selector de Símbolo (fijo a BTC/USDT por ahora), Selector de Temporalidad, Botón Añadir Indicador.
    *   **Área Principal**: El gráfico de velas.
    *   **Panel Derecho (Opcional)**: Lista de indicadores activos y sus configuraciones, o herramientas de dibujo.
    *   **Sub-Paneles (Debajo del gráfico principal)**: Para indicadores como RSI, MACD.

### 11.4 Vista: Monitor de Órdenes y Posiciones

*   **Propósito**: Mostrar información detallada sobre las órdenes abiertas, el historial de órdenes ejecutadas/canceladas, y las posiciones actuales del bot.
*   **Información Clave Mostrada**:
    *   **Tabla de Órdenes Abiertas**:
        *   Columnas: Símbolo, ID de Orden, Tipo (LIMIT, MARKET, STOP), Lado (BUY, SELL), Precio, Cantidad, Cantidad Llenada, Estado (NEW, PARTIALLY_FILLED), Fecha/Hora Creación, Posición (LONG, SHORT, BOTH).
    *   **Tabla de Historial de Órdenes**:
        *   Columnas: Similar a Órdenes Abiertas, pero con estados finales (FILLED, CANCELED, REJECTED, EXPIRED), Precio Promedio Llenado.
    *   **Tabla de Posiciones Actuales**:
        *   Columnas: Símbolo, Tamaño de Posición, Lado (LONG, SHORT), Precio de Entrada Promedio, Mark Price Actual, P&L No Realizado (USDT y %), Margen Usado, Nivel de Liquidación (si disponible).
*   **Elementos Interactivos**:
    *   Botón "Cancelar Orden Seleccionada" (para órdenes abiertas).
    *   Botón "Cancelar Todas las Órdenes Abiertas" (para un símbolo o global).
    *   Botón "Cerrar Posición Seleccionada" (ejecutaría una orden de mercado opuesta).
    *   Filtros para las tablas (ej. por símbolo, por fecha, por estado).
    *   Botón "Actualizar Datos".
*   **Esbozo General del Layout**:
    *   Uso de Pestañas para separar "Órdenes Abiertas", "Historial de Órdenes", "Posiciones".
    *   Cada pestaña contendría una tabla con la información respectiva.
    *   Botones de acción relevantes encima o debajo de cada tabla.

### 11.5 Vista: Interfaz de Backtesting

*   **Propósito**: Permitir al usuario configurar y ejecutar backtests de las estrategias sobre datos históricos, y visualizar los resultados.
*   **Información Clave Mostrada / Campos de Configuración**:
    *   **Configuración del Backtest**:
        *   Selector de Estrategia(s) a probar.
        *   Configuración de parámetros para la(s) estrategia(s) seleccionada(s) (similar a la vista de configuración de estrategias, pero específica para el backtest).
        *   Selector de Símbolo (fijo a BTC/USDT).
        *   Selector de Intervalo de Velas para el backtest.
        *   Selector de Rango de Fechas (Desde - Hasta) para los datos históricos.
        *   Campo para Capital Inicial del backtest.
        *   Campo para Comisiones (porcentaje por trade).
    *   **Resultados del Backtest (después de la ejecución)**:
        *   Resumen de Métricas: P&L Total, % Ganancia, Max Drawdown, Winrate, Sharpe Ratio, Número de Trades.
        *   Gráfico de Curva de Equidad (Equity Curve).
        *   Tabla/Lista de Trades Simulados: Símbolo, Fecha/Hora Entrada, Tipo (LONG/SHORT), Precio Entrada, Fecha/Hora Salida, Precio Salida, P&L del Trade.
*   **Elementos Interactivos**:
    *   Botón "Iniciar Backtest".
    *   Barra de Progreso durante la ejecución del backtest.
    *   Botón "Guardar Resultados del Backtest" (ej. a CSV).
    *   Botón "Cargar Configuración de Backtest".
    *   Controles para navegar por la lista de trades o el gráfico de equidad.
*   **Esbozo General del Layout**:
    *   **Panel Izquierdo (Configuración)**: Campos para seleccionar estrategia, fechas, capital, comisiones, parámetros de estrategia. Botón "Iniciar Backtest".
    *   **Área Derecha (Resultados)**:
        *   Pestaña "Resumen/Métricas": Muestra las métricas clave.
        *   Pestaña "Gráfico de Equidad": Muestra la curva de equidad.
        *   Pestaña "Lista de Trades": Muestra la tabla de trades.
    *   (Opcional) Una sección para logs específicos del backtest.
