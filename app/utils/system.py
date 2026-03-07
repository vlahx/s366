import psutil
import docker
import pynvml
import os

def get_nvme_status():
    usage = psutil.disk_usage('/')
    return {
        "device": "NVMe RAID",
        "total": round(usage.total / (1024**3), 2),
        "used": round(usage.used / (1024**3), 2),
        "free": round(usage.free / (1024**3), 2),
        "percent": usage.percent
    }

def get_gpu_status():
    """Monitorizează RTX 3060 Ti-ul tău și orice alt GPU de pe Dell T7910."""
    try:
        pynvml.nvmlInit()
        gpu_count = pynvml.nvmlDeviceGetCount()
        gpu_list = []
        
        for i in range(gpu_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            
            # Numele plăcii (ex: NVIDIA GeForce RTX 3060 Ti)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):  # Unele versiuni returnează bytes
                name = name.decode('utf-8')
                
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            
            # Mai băgăm o bibileală: Temperatura și Viteza Ventilatorului
            temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            try:
                fan_speed = pynvml.nvmlDeviceGetFanSpeed(handle)
            except:
                fan_speed = "N/A"  # Unele GPU-uri nu lasă citirea asta

            gpu_list.append({
                "index": i,
                "name": name,
                "vram_used_mb": round(mem_info.used / (1024**2), 1),
                "vram_total_mb": round(mem_info.total / (1024**2), 1),
                "vram_percent": round((mem_info.used / mem_info.total) * 100, 1),
                "load_percent": util.gpu,
                "temp_c": temp,
                "fan_percent": fan_speed
            })
            
        pynvml.nvmlShutdown()
        return gpu_list
    except Exception as e:
        # Nu lăsăm eroarea să crape tot app-ul dacă driverul e ocupat
        print(f"⚠️ [GPU MONITOR] Eroare NVML: {e}")
        return []
        return []

def get_docker_info():
    try:
        client = docker.from_env()
        return [{
            "name": c.name,
            "status": c.status,
            "image": c.image.tags[0] if c.image.tags else "N/A"
        } for c in client.containers.list(all=True)]
    except:
        return []

def get_system_stats():
    ram = psutil.virtual_memory()
    return {
        "cpu": psutil.cpu_percent(interval=None),
        "ram_percent": ram.percent,
        "ram_used": round(ram.used / (1024**3), 2),
        "ram_total": round(ram.total / (1024**3), 2),
        "nvme": get_nvme_status(),
        "gpus": get_gpu_status(),
        "docker": get_docker_info()
    }