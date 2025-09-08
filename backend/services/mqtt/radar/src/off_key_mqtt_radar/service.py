"""
Main RADAR Service Orchestrator

Coordinates MQTT subscription, anomaly detection, and database persistence
with comprehensive monitoring and health checks.
"""

import asyncio
import signal
import time
from datetime import datetime
from typing import Optional
from collections import deque

from off_key_core.config.logs import logger

from .config import radar_settings, AnomalyDetectionConfig
from .detector import AnomalyDetectionService, ResilientAnomalyDetector, MemoryManager, SecurityValidator
from .mqtt_client import RadarMQTTClient
from .database import DatabaseWriter, ensure_tables_exist
from .models import MQTTMessage, HealthStatus as RadarHealthStatus
from .config_watcher import ConfigWatcher, ConfigReloader


class RadarService:
    """
    Main RADAR service orchestrator
    
    Coordinates:
    - MQTT message subscription and processing
    - Anomaly detection pipeline
    - Database persistence
    - Health monitoring and alerts
    - Resource management
    """
    
    def __init__(self):
        self.config = radar_settings.config
        
        # Core components
        self.mqtt_client: Optional[RadarMQTTClient] = None
        self.detector: Optional[ResilientAnomalyDetector] = None
        self.database_writer: Optional[DatabaseWriter] = None
        
        # Supporting components
        self.memory_manager = MemoryManager(
            max_memory_mb=self.config.memory_limit_mb,
            cleanup_threshold=0.8
        )
        self.security_validator = SecurityValidator(
            max_feature_count=self.config.max_feature_count,
            max_string_length=self.config.max_string_length
        )
        
        # Service state
        self.is_running = False
        self.start_time: Optional[datetime] = None
        self.shutdown_event = asyncio.Event()
        
        # Performance tracking
        self.message_count = 0
        self.anomaly_count = 0
        self.error_count = 0
        self.processing_times = deque(maxlen=1000)
        
        # Health monitoring
        self.health_check_task: Optional[asyncio.Task] = None
        self.last_health_check = time.time()
        
        # Configuration watching and reloading
        self.config_watcher: Optional[ConfigWatcher] = None
        self.config_reloader: Optional[ConfigReloader] = None
        
        # Logging context
        self._log_context = {"service": "radar", "component": "main"}
        
        logger.info("Initialized RADAR service orchestrator")
    
    async def start(self):
        """Start the RADAR service"""
        if self.is_running:
            logger.warning("RADAR service already running")
            return
        
        logger.info("Starting RADAR service", extra=self._log_context)
        self.start_time = datetime.now()
        
        try:
            # Ensure database tables exist
            await ensure_tables_exist()
            
            # Initialize anomaly detection
            await self._setup_anomaly_detection()
            
            # Initialize database writer
            await self._setup_database_writer()
            
            # Initialize MQTT client
            await self._setup_mqtt_client()
            
            # Start health monitoring
            self.health_check_task = asyncio.create_task(self._health_monitor())
            
            # Setup configuration watching
            await self._setup_config_watcher()
            
            self.is_running = True
            
            logger.info(
                "RADAR service started successfully",
                extra={
                    **self._log_context,
                    "subscribed_topics": self.config.subscription_topics,
                    "model_type": self.config.model_type,
                    "db_enabled": self.config.db_write_enabled,
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to start RADAR service: {e}", extra=self._log_context)
            await self.stop()
            raise
    
    async def stop(self):
        """Stop the RADAR service"""
        if not self.is_running:
            logger.info("RADAR service already stopped")
            return
        
        logger.info("Stopping RADAR service", extra=self._log_context)
        
        # Signal shutdown
        self.shutdown_event.set()
        self.is_running = False
        
        # Stop components in reverse order
        components = [
            ("config_watcher", self.config_watcher),
            ("health_monitor", self.health_check_task),
            ("mqtt_client", self.mqtt_client),
            ("database_writer", self.database_writer),
        ]
        
        for component_name, component in components:
            if component:
                try:
                    if hasattr(component, 'stop'):
                        await component.stop()
                    elif hasattr(component, 'cancel'):
                        component.cancel()
                        try:
                            await component
                        except asyncio.CancelledError:
                            pass
                    
                    logger.info(f"Stopped {component_name}")
                except Exception as e:
                    logger.error(f"Error stopping {component_name}: {e}")
        
        logger.info("RADAR service stopped")
    
    async def _setup_anomaly_detection(self):
        """Initialize anomaly detection components"""
        logger.info("Setting up anomaly detection")
        
        # Create anomaly detection config
        anomaly_config = AnomalyDetectionConfig(
            model_type=getattr(self.config, 'model_type', 'isolation_forest'),
            thresholds=getattr(self.config, 'thresholds', {
                "medium": 0.6,
                "high": 0.8, 
                "critical": 0.9
            }),
            batch_size=getattr(self.config, 'batch_size', 100),
            batch_timeout=getattr(self.config, 'batch_timeout', 1.0),
            memory_limit_mb=getattr(self.config, 'memory_limit_mb', 1000),
            checkpoint_interval=getattr(self.config, 'checkpoint_interval', 10000),
        )
        
        # Create primary service
        primary_service = AnomalyDetectionService(anomaly_config)
        
        # Create resilient detector (with fallback)
        self.detector = ResilientAnomalyDetector(primary_service)
        
        logger.info(f"Anomaly detection setup complete with model: {anomaly_config.model_type}")
    
    async def _setup_database_writer(self):
        """Initialize database writer"""
        logger.info("Setting up database writer")
        
        self.database_writer = DatabaseWriter(self.config)
        await self.database_writer.start()
        
        logger.info("Database writer setup complete")
    
    async def _setup_mqtt_client(self):
        """Initialize MQTT client and message handling"""
        logger.info("Setting up MQTT client")
        
        self.mqtt_client = RadarMQTTClient(self.config)
        self.mqtt_client.set_message_handler(self._handle_mqtt_message)
        await self.mqtt_client.start()
        
        logger.info("MQTT client setup complete")
    
    async def _setup_config_watcher(self):
        """Setup configuration file watching for hot reload"""
        try:
            # Check if we have a config file to watch
            config_file_path = getattr(radar_settings, 'custom_config_file', None)
            
            if not config_file_path:
                logger.info("No configuration file specified for watching")
                return
            
            logger.info(f"Setting up configuration file watcher for: {config_file_path}")
            
            # Create config reloader
            self.config_reloader = ConfigReloader(self)
            
            # Create config watcher
            self.config_watcher = ConfigWatcher(
                config_file_path,
                self.config_reloader.reload_config
            )
            
            # Start watching
            await self.config_watcher.start()
            
            logger.info("Configuration file watcher setup complete")
            
        except Exception as e:
            logger.error(f"Failed to setup configuration watcher: {e}")
            # Don't fail the service startup if config watching fails
    
    async def _handle_mqtt_message(self, message: MQTTMessage):
        """Handle incoming MQTT message"""
        start_time = time.time()
        
        try:
            # Parse JSON payload
            try:
                data = message.get_json_payload()
            except ValueError as e:
                logger.debug(f"Invalid JSON payload from {message.topic}: {e}")
                self.error_count += 1
                return
            
            # Validate and sanitize input
            try:
                sanitized_data = self.security_validator.validate_and_sanitize(data)
                if not sanitized_data:
                    logger.debug(f"No valid features in message from {message.topic}")
                    return
            except ValueError as e:
                logger.debug(f"Security validation failed for {message.topic}: {e}")
                self.error_count += 1
                return
            
            # Extract charger ID from topic
            charger_id = message.extract_charger_id()
            
            # Process with anomaly detection
            result = self.detector.process_with_resilience(
                sanitized_data,
                topic=message.topic,
                charger_id=charger_id
            )
            
            # Record processing time
            processing_time = time.time() - start_time
            self.processing_times.append(processing_time)
            
            # Update counters
            self.message_count += 1
            if result.is_anomaly:
                self.anomaly_count += 1
            
            # Write to database if anomaly detected or configured to write all
            if result.is_anomaly or getattr(self.config, 'write_all_results', False):
                if self.database_writer:
                    await self.database_writer.write_anomaly(result)
            
            # Log significant anomalies
            if result.is_anomaly and result.severity in ['high', 'critical']:
                logger.warning(
                    f"Significant anomaly detected: score={result.anomaly_score:.3f}, "
                    f"severity={result.severity}, topic={message.topic}, charger={charger_id}",
                    extra={
                        **self._log_context,
                        "anomaly_score": result.anomaly_score,
                        "severity": result.severity,
                        "topic": message.topic,
                        "charger_id": charger_id,
                    }
                )
            
            # Memory cleanup check
            if self.memory_manager.should_cleanup():
                freed = self.memory_manager.force_cleanup()
                logger.info(f"Memory cleanup freed {freed:.1f} MB")
            
        except Exception as e:
            logger.error(f"Error processing message from {message.topic}: {e}", exc_info=True)
            self.error_count += 1
    
    async def _health_monitor(self):
        """Periodic health monitoring and metrics collection"""
        logger.info("Started health monitor")
        
        try:
            while not self.shutdown_event.is_set():
                try:
                    # Wait for health check interval
                    await asyncio.wait_for(
                        self.shutdown_event.wait(),
                        timeout=self.config.health_check_interval
                    )
                    break  # Shutdown event was set
                except asyncio.TimeoutError:
                    # Perform health check
                    await self._perform_health_check()
                
        except asyncio.CancelledError:
            logger.info("Health monitor cancelled")
        except Exception as e:
            logger.error(f"Health monitor error: {e}")
        
        logger.info("Health monitor stopped")
    
    async def _perform_health_check(self):
        """Perform comprehensive health check"""
        try:
            health_status = self.get_health_status()
            
            # Log health status
            if health_status.status in ['degraded', 'failed']:
                logger.warning(f"Service health: {health_status.status}", extra=self._log_context)
                for alert in health_status.active_alerts:
                    logger.warning(f"Active alert: {alert}", extra=self._log_context)
            else:
                logger.debug(f"Service health: {health_status.status}", extra=self._log_context)
            
            # Write metrics to database
            if self.database_writer and health_status.status != 'failed':
                metrics = {
                    'total_messages_processed': self.message_count,
                    'total_anomalies_detected': self.anomaly_count,
                    'anomaly_rate': self.anomaly_count / max(self.message_count, 1),
                    'avg_processing_time_ms': sum(self.processing_times) / max(len(self.processing_times), 1) * 1000,
                    'throughput_per_second': self._calculate_throughput(),
                    'memory_usage_mb': self.memory_manager.get_memory_usage(),
                    'error_count': self.error_count,
                    'error_rate': self.error_count / max(self.message_count, 1),
                    'service_status': health_status.status,
                    'active_alerts': health_status.active_alerts,
                }
                
                await self.database_writer.write_service_metrics(metrics)
            
            self.last_health_check = time.time()
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
    
    def _calculate_throughput(self) -> float:
        """Calculate current message processing throughput"""
        if not self.start_time:
            return 0.0
        
        uptime = (datetime.now() - self.start_time).total_seconds()
        if uptime <= 0:
            return 0.0
        
        return self.message_count / uptime
    
    async def run(self):
        """Run the RADAR service with signal handling"""
        # Set up signal handlers
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating graceful shutdown")
            asyncio.create_task(self.stop())
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        try:
            # Start the service
            await self.start()
            
            # Keep running until shutdown
            await self.shutdown_event.wait()
            
        except Exception as e:
            logger.error(f"Unexpected error in RADAR service: {e}", exc_info=True)
        finally:
            # Ensure cleanup
            await self.stop()
    
    def get_health_status(self) -> RadarHealthStatus:
        """Get comprehensive health status"""
        components = {}
        active_alerts = []
        
        # Check MQTT client
        if self.mqtt_client:
            mqtt_health = self.mqtt_client.get_health_status()
            components['mqtt_client'] = mqtt_health
            if mqtt_health['status'] != 'healthy':
                active_alerts.append(f"mqtt_{mqtt_health['reason']}")
        
        # Check database writer
        if self.database_writer:
            db_health = self.database_writer.get_health_status()
            components['database_writer'] = db_health
            if db_health['status'] != 'healthy' and db_health['status'] != 'disabled':
                active_alerts.append(f"database_{db_health['reason']}")
        
        # Check anomaly detector
        if self.detector:
            detector_health = self.detector.get_health_info()
            components['anomaly_detector'] = detector_health
            if detector_health['state'] != 'healthy':
                active_alerts.append(f"detector_{detector_health['state']}")
        
        # Check memory usage
        memory_usage = self.memory_manager.get_memory_usage()
        if memory_usage > self.memory_manager.max_memory_mb * 0.9:
            active_alerts.append("high_memory_usage")
        
        # Check error rate
        error_rate = self.error_count / max(self.message_count, 1)
        if error_rate > 0.1:  # > 10% error rate
            active_alerts.append("high_error_rate")
        
        # Determine overall status
        if not self.is_running:
            status = "failed"
        elif active_alerts:
            status = "degraded"
        else:
            status = "healthy"
        
        # Calculate metrics
        uptime = 0.0
        if self.start_time:
            uptime = (datetime.now() - self.start_time).total_seconds()
        
        avg_processing_time = 0.0
        if self.processing_times:
            avg_processing_time = sum(self.processing_times) / len(self.processing_times) * 1000
        
        metrics = {
            "uptime_seconds": uptime,
            "message_count": self.message_count,
            "anomaly_count": self.anomaly_count,
            "anomaly_rate": self.anomaly_count / max(self.message_count, 1),
            "error_count": self.error_count,
            "error_rate": error_rate,
            "avg_processing_time_ms": avg_processing_time,
            "throughput_per_second": self._calculate_throughput(),
            "memory_usage_mb": memory_usage,
        }
        
        return RadarHealthStatus(
            status=status,
            timestamp=datetime.now(),
            components=components,
            metrics=metrics,
            active_alerts=active_alerts,
            uptime_seconds=uptime
        )


# Global service instance
_radar_service: Optional[RadarService] = None


def get_radar_service() -> RadarService:
    """Get the global RADAR service instance"""
    global _radar_service
    if _radar_service is None:
        _radar_service = RadarService()
    return _radar_service