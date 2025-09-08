"""
MQTT RADAR Anomaly Detection Service

Implements anomaly detection patterns from guide.md for real-time processing
of MQTT telemetry data with resilient error handling and monitoring.
"""

import logging
import time
import pickle
import os
import psutil
import gc
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional
from collections import deque
from enum import Enum

# ONAD imports for online anomaly detection
try:
    from onad.models.online_isolation_forest import OnlineIsolationForest
    from onad.models.incremental_one_class_svm import IncrementalOneClassSVMAdaptiveKernel
    from onad.models.incremental_knn import IncrementalKNN
    from onad.transform.preprocess.scaler import StandardScaler
    from onad.transform.project.incremental_pca import IncrementalPCA
except ImportError as e:
    logging.warning(f"ONAD not available: {e}. Using mock implementations.")
    
    # Mock implementations for development
    class OnlineIsolationForest:
        def __init__(self, **kwargs): self.params = kwargs
        def learn_one(self, x): pass
        def score_one(self, x): return 0.5
    
    class IncrementalOneClassSVMAdaptiveKernel:
        def __init__(self, **kwargs): self.params = kwargs
        def learn_one(self, x): pass
        def score_one(self, x): return 0.5
    
    class IncrementalKNN:
        def __init__(self, **kwargs): self.params = kwargs
        def learn_one(self, x): pass
        def score_one(self, x): return 0.5
    
    class StandardScaler:
        def __init__(self, **kwargs): self.params = kwargs
        def learn_one(self, x): pass
        def transform_one(self, x): return x
    
    class IncrementalPCA:
        def __init__(self, **kwargs): self.params = kwargs
        def learn_one(self, x): pass
        def transform_one(self, x): return x

from .config import AnomalyDetectionConfig
from .models import AnomalyResult, MQTTMessage


class ServiceState(Enum):
    """Service health states"""
    HEALTHY = "healthy"
    DEGRADED = "degraded" 
    FAILED = "failed"
    UNKNOWN = "unknown"


class AnomalyDetectionService:
    """
    Core anomaly detection service following guide.md patterns
    
    Implements:
    - Multiple model support (Isolation Forest, SVM, KNN)
    - Preprocessing pipeline
    - Memory management
    - Model checkpointing
    - Performance monitoring
    """
    
    def __init__(self, config: AnomalyDetectionConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Initialize components
        self.model = self._create_model()
        self.preprocessors = self._create_preprocessors()
        
        # Monitoring
        self.processed_count = 0
        self.anomaly_count = 0
        self.last_checkpoint = 0
        self.start_time = time.time()
        
        # Performance tracking
        self.processing_times = deque(maxlen=1000)
        
        self.logger.info(f"Initialized anomaly detection service with model: {config.model_type}")
    
    def _create_model(self):
        """Factory method for model creation"""
        model_map = {
            'isolation_forest': OnlineIsolationForest,
            'adaptive_svm': IncrementalOneClassSVMAdaptiveKernel,
            'knn': IncrementalKNN
        }
        
        model_class = model_map.get(self.config.model_type)
        if not model_class:
            raise ValueError(f"Unknown model type: {self.config.model_type}")
        
        return model_class(**self.config.model_params)
    
    def _create_preprocessors(self):
        """Create preprocessing pipeline"""
        preprocessors = []
        for step in self.config.preprocessing_steps:
            if step['type'] == 'scaler':
                preprocessors.append(StandardScaler(**step.get('params', {})))
            elif step['type'] == 'pca':
                preprocessors.append(IncrementalPCA(**step.get('params', {})))
        
        return preprocessors
    
    def process_data_point(self, data: Dict[str, float], topic: str = None, charger_id: str = None) -> AnomalyResult:
        """Process single data point and return anomaly result"""
        start_time = time.time()
        
        try:
            # Preprocessing
            processed_data = data.copy()
            for preprocessor in self.preprocessors:
                preprocessor.learn_one(processed_data)
                processed_data = preprocessor.transform_one(processed_data)
            
            # Anomaly detection
            self.model.learn_one(processed_data)
            score = self.model.score_one(processed_data)
            
            # Thresholding
            is_anomaly = score > self.config.thresholds.get('medium', 0.6)
            severity = self._calculate_severity(score)
            
            # Update counters
            self.processed_count += 1
            if is_anomaly:
                self.anomaly_count += 1
            
            # Record processing time
            processing_time = time.time() - start_time
            self.processing_times.append(processing_time)
            
            # Periodic operations
            if self.processed_count % self.config.checkpoint_interval == 0:
                self._checkpoint_model()
            
            # Create result
            result = AnomalyResult(
                anomaly_score=score,
                is_anomaly=is_anomaly,
                severity=severity,
                timestamp=datetime.now(),
                model_info=self._get_model_info(),
                raw_data=data,
                processed_features=processed_data,
                topic=topic,
                charger_id=charger_id,
                context={
                    'processing_time_ms': processing_time * 1000,
                    'model_type': self.config.model_type,
                }
            )
            
            if is_anomaly:
                self.logger.warning(
                    f"Anomaly detected: score={score:.3f}, severity={severity}, topic={topic}"
                )
            
            return result
            
        except Exception as e:
            self.logger.error(f"Processing error: {e}")
            return AnomalyResult(
                anomaly_score=0.0,
                is_anomaly=False,
                severity='unknown',
                timestamp=datetime.now(),
                model_info={'error': str(e)},
                raw_data=data,
                topic=topic,
                charger_id=charger_id,
                context={'error': str(e), 'processing_time_ms': (time.time() - start_time) * 1000}
            )
    
    def _calculate_severity(self, score: float) -> str:
        """Calculate anomaly severity level"""
        thresholds = self.config.thresholds
        
        if score > thresholds.get('critical', 0.9):
            return 'critical'
        elif score > thresholds.get('high', 0.8):
            return 'high'
        elif score > thresholds.get('medium', 0.6):
            return 'medium'
        else:
            return 'low'
    
    def _checkpoint_model(self):
        """Save model checkpoint"""
        try:
            checkpoint_dir = 'checkpoints'
            os.makedirs(checkpoint_dir, exist_ok=True)
            
            checkpoint_path = f"{checkpoint_dir}/model_{self.processed_count}_{int(time.time())}.pkl"
            with open(checkpoint_path, 'wb') as f:
                pickle.dump({
                    'model': self.model,
                    'preprocessors': self.preprocessors,
                    'processed_count': self.processed_count,
                    'anomaly_count': self.anomaly_count,
                    'config': self.config
                }, f)
            
            self.logger.info(f"Model checkpoint saved: {checkpoint_path}")
            
        except Exception as e:
            self.logger.error(f"Failed to save checkpoint: {e}")
    
    def _get_model_info(self) -> Dict[str, Any]:
        """Get model state information"""
        return {
            'processed_count': self.processed_count,
            'anomaly_count': self.anomaly_count,
            'anomaly_rate': self.anomaly_count / max(self.processed_count, 1),
            'memory_usage_mb': self._get_memory_usage(),
            'avg_processing_time_ms': sum(self.processing_times) / max(len(self.processing_times), 1) * 1000,
            'uptime_seconds': time.time() - self.start_time,
        }
    
    def _get_memory_usage(self) -> float:
        """Get current memory usage in MB"""
        try:
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / 1024 / 1024
        except Exception:
            return 0.0


class ResilientAnomalyDetector:
    """
    Resilient anomaly detector with error handling and fallback mechanisms
    Implements circuit breaker pattern from guide.md
    """
    
    def __init__(self, primary_service: AnomalyDetectionService, fallback_service: Optional[AnomalyDetectionService] = None):
        self.primary_service = primary_service
        self.fallback_service = fallback_service
        self.state = ServiceState.HEALTHY
        
        # Error tracking
        self.error_count = 0
        self.error_window = 100
        self.error_threshold = 0.1  # 10% error rate
        self.last_errors = deque(maxlen=self.error_window)
        
        # Circuit breaker
        self.circuit_breaker_open = False
        self.circuit_breaker_timeout = 300  # 5 minutes
        self.circuit_breaker_opened_at = None
        
        self.logger = logging.getLogger(__name__)
    
    def process_with_resilience(self, data: Dict[str, float], topic: str = None, charger_id: str = None) -> AnomalyResult:
        """Process data point with error handling and fallback"""
        try:
            # Check circuit breaker
            if self._should_use_circuit_breaker():
                return self._fallback_processing(data, topic, charger_id, "circuit_breaker")
            
            # Try primary service
            result = self.primary_service.process_data_point(data, topic, charger_id)
            self._record_success()
            
            return result
            
        except Exception as e:
            self._record_error(e)
            
            # Try fallback processing
            return self._fallback_processing(data, topic, charger_id, str(e))
    
    def _fallback_processing(self, data: Dict[str, float], topic: str, charger_id: str, reason: str) -> AnomalyResult:
        """Fallback processing when primary fails"""
        self.logger.warning(f"Using fallback processing: {reason}")
        
        try:
            if self.fallback_service:
                result = self.fallback_service.process_data_point(data, topic, charger_id)
                result.context = result.context or {}
                result.context['fallback_reason'] = reason
                result.context['model_used'] = 'fallback'
                return result
            else:
                # Simple statistical fallback
                score = self._simple_statistical_anomaly_score(data)
                return AnomalyResult(
                    anomaly_score=score,
                    is_anomaly=score > 0.7,
                    severity='medium' if score > 0.7 else 'low',
                    timestamp=datetime.now(),
                    model_info={'model_used': 'statistical'},
                    raw_data=data,
                    topic=topic,
                    charger_id=charger_id,
                    context={
                        'fallback_reason': reason,
                        'model_used': 'statistical',
                        'service_state': ServiceState.DEGRADED.value
                    }
                )
                
        except Exception as e:
            self.logger.error(f"Fallback processing failed: {e}")
            return AnomalyResult(
                anomaly_score=0.0,
                is_anomaly=False,
                severity='unknown',
                timestamp=datetime.now(),
                model_info={'error': str(e), 'model_used': 'none'},
                raw_data=data,
                topic=topic,
                charger_id=charger_id,
                context={
                    'error': str(e),
                    'fallback_reason': reason,
                    'service_state': ServiceState.FAILED.value
                }
            )
    
    def _simple_statistical_anomaly_score(self, data: Dict[str, float]) -> float:
        """Simple statistical anomaly detection as last resort"""
        try:
            import numpy as np
            
            values = list(data.values())
            if not hasattr(self, '_running_mean'):
                self._running_mean = np.mean(values)
                self._running_std = 1.0
                self._count = 1
                return 0.0
            
            # Update running statistics
            current_mean = np.mean(values)
            self._count += 1
            alpha = 1.0 / min(self._count, 100)  # Cap the learning rate
            self._running_mean = (1 - alpha) * self._running_mean + alpha * current_mean
            
            # Calculate anomaly score based on deviation
            deviation = abs(current_mean - self._running_mean)
            score = min(deviation / (self._running_std + 1e-8), 1.0)
            return score
            
        except Exception:
            return 0.0
    
    def _record_error(self, error: Exception):
        """Record error for circuit breaker logic"""
        self.error_count += 1
        self.last_errors.append(time.time())
        
        # Check if we should open circuit breaker
        recent_error_rate = len(self.last_errors) / self.error_window
        if recent_error_rate > self.error_threshold:
            self._open_circuit_breaker()
        
        self.logger.error(f"Model error: {error}")
    
    def _record_success(self):
        """Record successful processing"""
        if self.circuit_breaker_open:
            # Try to close circuit breaker
            self._close_circuit_breaker()
    
    def _should_use_circuit_breaker(self) -> bool:
        """Check if circuit breaker should prevent primary model use"""
        if not self.circuit_breaker_open:
            return False
        
        # Check if timeout has passed
        if (time.time() - self.circuit_breaker_opened_at) > self.circuit_breaker_timeout:
            self._close_circuit_breaker()
            return False
        
        return True
    
    def _open_circuit_breaker(self):
        """Open circuit breaker"""
        self.circuit_breaker_open = True
        self.circuit_breaker_opened_at = time.time()
        self.state = ServiceState.DEGRADED
        self.logger.warning("Circuit breaker opened - using fallback processing")
    
    def _close_circuit_breaker(self):
        """Close circuit breaker"""
        self.circuit_breaker_open = False
        self.circuit_breaker_opened_at = None
        self.state = ServiceState.HEALTHY
        self.logger.info("Circuit breaker closed - resuming normal processing")
    
    def get_service_state(self) -> ServiceState:
        """Get current service state"""
        return self.state
    
    def get_health_info(self) -> Dict[str, Any]:
        """Get health information"""
        return {
            'state': self.state.value,
            'circuit_breaker_open': self.circuit_breaker_open,
            'error_count': self.error_count,
            'recent_error_rate': len(self.last_errors) / self.error_window,
            'primary_service_stats': self.primary_service._get_model_info(),
            'uptime_seconds': time.time() - getattr(self, 'start_time', time.time()),
        }


class MemoryManager:
    """Memory management utilities following guide.md patterns"""
    
    def __init__(self, max_memory_mb=2000, cleanup_threshold=0.8):
        self.max_memory_mb = max_memory_mb
        self.cleanup_threshold = cleanup_threshold
        self.process = psutil.Process(os.getpid())
        self.logger = logging.getLogger(__name__)
    
    def get_memory_usage(self) -> float:
        """Get current memory usage in MB"""
        return self.process.memory_info().rss / 1024 / 1024
    
    def should_cleanup(self) -> bool:
        """Check if memory cleanup is needed"""
        current_memory = self.get_memory_usage()
        return current_memory > (self.max_memory_mb * self.cleanup_threshold)
    
    def force_cleanup(self) -> float:
        """Force garbage collection and memory cleanup"""
        before_memory = self.get_memory_usage()
        
        # Run garbage collection
        collected = gc.collect()
        
        after_memory = self.get_memory_usage()
        freed_memory = before_memory - after_memory
        
        self.logger.info(
            f"Memory cleanup: freed {freed_memory:.1f} MB, collected {collected} objects"
        )
        
        return freed_memory


class SecurityValidator:
    """Input validation and sanitization following guide.md patterns"""
    
    def __init__(self, max_feature_count=100, max_string_length=1000):
        self.max_feature_count = max_feature_count
        self.max_string_length = max_string_length
        self.logger = logging.getLogger(__name__)
    
    def validate_and_sanitize(self, data: Dict[str, Any]) -> Dict[str, float]:
        """Validate and sanitize input data to numeric format"""
        if not isinstance(data, dict):
            raise ValueError("Input must be a dictionary")
        
        if len(data) > self.max_feature_count:
            raise ValueError(f"Too many features: {len(data)} > {self.max_feature_count}")
        
        sanitized = {}
        
        for key, value in data.items():
            # Validate key
            if not isinstance(key, str) or len(key) > 100:
                continue  # Skip invalid keys
            
            # Convert value to float
            try:
                if isinstance(value, (int, float)):
                    if -1e10 < value < 1e10:  # Reasonable range
                        sanitized[key] = float(value)
                elif isinstance(value, str):
                    if len(value) > self.max_string_length:
                        continue  # Skip overly long strings
                    
                    # Try to convert to float
                    try:
                        sanitized[key] = float(value)
                    except ValueError:
                        # Hash string to numeric value
                        hash_val = int(hashlib.md5(value.encode()).hexdigest()[:8], 16)
                        sanitized[key] = float(hash_val % 10000)
                elif isinstance(value, bool):
                    sanitized[key] = float(value)
            except Exception as e:
                self.logger.debug(f"Skipping invalid feature {key}: {e}")
                continue
        
        return sanitized