# CARLA RAG Pipeline - Scenario Generator

A complete RAG (Retrieval-Augmented Generation) pipeline for automatically generating CARLA driving simulation scenarios using Google Gemini API and LangChain.

## 🎯 Features

- **Intelligent Scenario Matching**: Uses semantic search to find the best scenario template
- **Natural Language Processing**: Understands plain English requests like "2 cars in rainy weather"
- **Immediate Code Generation**: Generates ready-to-run CARLA Python scripts
- **Template-Based Reliability**: Uses proven code templates to ensure generated code always works
- **Comprehensive Testing**: Built-in syntax validation and structure verification
- **Dataset Creation**: Automatically saves simulation frames for machine learning datasets
5. **Frame Saving**: Automatically saves simulation frames for dataset creation
6. **JSON Database**: Fast POC with expandable scenario templates

## 📁 Project Structure

```
rag_scenerio_generator/
├── venv_langchain/              # Python 3.13 virtual environment (ready to use)
├── simple_carla_rag_demo.py     # Simple RAG demo (for learning)
├── reliable_template_rag.py     # Production RAG system (recommended)
├── test_generated_code.py       # Code validation testing
├── requirements.txt             # Python dependencies
├── .env                         # API keys (already configured)
└── README.md                    # This documentation

../
├── carla_scenarios_db.json      # Scenario database (5 templates)
├── generated_scenarios/         # Generated CARLA scripts 
│   ├── reliable_night-driving_*.py
│   └── improved_rainy_two_cars.py
└── editable_simulation_output/   # Simulation frame outputs
```

## 🚀 Quick Start

### 1. Prerequisites

- **CARLA Simulator** (any recent version)
- **Python 3.8+** (for generated scripts)
- **Python 3.13** (for RAG pipeline - already set up)
- **Google Gemini API Key** (already configured)

### 2. Setup Virtual Environment

The virtual environment is already configured! Just activate it:

```bash
cd rag_scenerio_generator
venv_langchain\Scripts\activate
```

### 3. Run the RAG System

```bash
# Simple demo version (for learning)
venv_langchain\Scripts\python.exe simple_carla_rag_demo.py

# Reliable template-based version (recommended)
venv_langchain\Scripts\python.exe reliable_template_rag.py

# Test generated code quality
venv_langchain\Scripts\python.exe test_generated_code.py
```

## 💡 Usage Examples

### Example Requests:
1. "2 cars driving in rainy weather and camera following from third person view"
2. "Multiple vehicles at intersection with overhead camera"  
3. "Night driving with 3 vehicles and headlights"
4. "Single car in sunny weather"

### System Response:
The RAG pipeline will:
1. 🧠 **Understand** your request
2. 🔍 **Find** the best matching scenario  
3. 🔧 **Generate** complete CARLA code
4. ✅ **Validate** syntax and structure
5. 💾 **Save** ready-to-run script

## 🎮 Running Generated Scenarios

### Step 1: Start CARLA Server
```bash
# Start CARLA (adjust path as needed)
CarlaUE4.exe
```

### Step 2: Run Generated Script
```bash
cd generated_scenarios

# Run with default settings (30 seconds)
python reliable_night-driving_1754451658.py

# Run with custom duration
python reliable_night-driving_1754451658.py --duration 60

# Run with custom output directory  
python reliable_night-driving_1754451658.py --output my_dataset
```

### Step 3: Access Generated Dataset
- Frames are saved as PNG images
- Default location: `scenario-name-frames/`
- Format: `frame_000000.png`, `frame_000001.png`, etc.

### 3. Test the Setup

```powershell
python test_rag_setup.py
```

Expected output:
```
✅ Gemini API working: Hello from Gemini!
✅ Scenarios DB loaded: 5 scenarios
✅ All tests passed! RAG system ready to use.
```

### 4. Run the Demo

```powershell
python simple_carla_rag_demo.py
```

### 5. Try Example Requests

- "2 cars driving in rainy weather and camera following from third person view"
- "Multiple vehicles at an intersection with overhead camera"
- "Night driving with vehicle lights"
- "Single car on a straight road in sunny weather"

## 🔧 How It Works

### RAG Pipeline Flow

1. **🧠 Natural Language Understanding**
   - User inputs scenario description
   - Gemini analyzes and extracts requirements
   - System parses vehicle count, weather, camera mode, etc.

2. **🔍 Scenario Retrieval**
   - Searches JSON database for matching scenarios
   - Uses semantic similarity to find best match
   - Returns scenario template with parameters

3. **💡 Explainable Understanding**
   - Shows what the system understood
   - Explains the selected scenario and configuration
   - Displays execution plan and safety checks

4. **🔧 Code Generation**
   - Generates complete CARLA Python script
   - Includes proper error handling and cleanup
   - Compatible with Python 3.8
   - Implements frame saving for dataset creation

5. **💾 Output & Execution**
   - Saves generated code to `generated_scenarios/`
   - Ready to run with CARLA server
   - Automatically creates frame output directories

### Example Flow

```
User Input: "2 cars driving in rainy weather and camera following from third person view"
           ↓
🧠 Understanding: Two cars, rainy weather, third-person camera
           ↓
🔍 Retrieval: Matches "rainy_two_cars" scenario (95% similarity)
           ↓
💡 Explanation: Will spawn 2 vehicles, set 80% precipitation, attach following camera
           ↓
🔧 Generation: Creates complete CARLA Python script
           ↓
💾 Output: Saves to generated_scenarios/rainy_two_cars_<timestamp>.py
```

## 📊 Scenario Database

The system uses `carla_scenarios_db.json` with predefined scenario templates:

```json
{
  "scenarios": [
    {
      "id": "rainy_two_cars",
      "description": "Two cars driving in rainy weather with third person camera",
      "keywords": ["two cars", "rainy", "rain", "weather", "third person", "follow"],
      "code_template": "spawn_multiple_vehicles_weather",
      "parameters": {
        "vehicle_count": 2,
        "weather": "rain",
        "camera_mode": "follow_car",
        "speed_multiplier": 1.0,
        "precipitation": 80.0
      }
    }
  ]
}
```

## 🎮 Running Generated Scenarios

Generated scripts are saved to `generated_scenarios/` and can be run with Python 3.8:

1. **Start CARLA Server** (usually on localhost:2000)
2. **Switch to Python 3.8 environment**
3. **Run the generated script**:

```bash
cd generated_scenarios
python rainy_two_cars_clean.py --duration 60
```

### Generated Script Features

- ✅ Connects to CARLA server with error handling
- ✅ Spawns specified number of vehicles
- ✅ Sets weather conditions (rain, snow, fog, etc.)
- ✅ Configures camera positioning (first-person, third-person, overhead)
- ✅ Saves frames to `frames_output/` directory
- ✅ Proper resource cleanup
- ✅ Detailed logging and progress updates

## 🔧 API Configuration

The system uses Google Gemini API for language understanding and code generation:

```bash
# In .env file
GOOGLE_API_KEY=AIzaSyCFehRM1QrpPMkKiMPXJXiXq_n7CblmNZo
```

## 📈 Extending the System

### Adding New Scenarios

1. **Edit `carla_scenarios_db.json`**:
```json
{
  "id": "highway_traffic",
  "description": "Heavy traffic on highway with multiple lanes",
  "keywords": ["highway", "traffic", "multiple lanes", "busy"],
  "code_template": "spawn_highway_traffic",
  "parameters": {
    "vehicle_count": 15,
    "weather": "clear",
    "camera_mode": "overhead",
    "speed_multiplier": 0.8
  }
}
```

2. **Restart the RAG system** to load new scenarios

### Customizing Code Generation

Modify the prompt in `simple_carla_rag_demo.py`:

```python
def generate_carla_code(self, user_input: str, scenario: dict):
    prompt = f"""
    Generate a complete Python script for CARLA simulator...
    [Add your custom requirements here]
    """
```

## � System Components

### 1. RAG Pipeline (`reliable_template_rag.py`) - **RECOMMENDED**
- **Template-Based Generation**: Uses proven code templates
- **Syntax Validation**: Guarantees error-free code  
- **Gemini Integration**: Natural language understanding
- **Scenario Matching**: Smart template selection

### 2. Simple Demo (`simple_carla_rag_demo.py`)
- **Learning Tool**: Shows RAG concepts clearly
- **Direct Generation**: Uses Gemini to write code from scratch
- **Educational**: Good for understanding the pipeline

### 3. Scenario Database (`carla_scenarios_db.json`)
- 5 pre-configured scenario templates
- Weather variations (rain, snow, fog, night, clear)
- Camera modes (follow_car, overhead, first_person)
- Vehicle configurations (1-5 vehicles)

### 4. Generated Scripts
- **Python 3.8 Compatible**: Runs with CARLA Python API
- **Command Line Interface**: Configurable duration, output
- **Error Handling**: Robust connection and spawning logic
- **Progress Tracking**: Real-time status updates
- **Resource Cleanup**: Proper actor destruction

## 🛠️ Dependencies

### RAG Pipeline (Python 3.13) - Already Installed ✅
```
langchain==0.3.12
google-generativeai==0.8.3  
chromadb==0.5.23
sentence-transformers==3.3.1
python-dotenv==1.0.1
```

### Generated Scripts (Python 3.8)
```
carla==0.9.x  # CARLA Python API
```

## 🧪 Testing

### Validate Generated Code
```bash
venv_langchain\Scripts\python.exe test_generated_code.py
```

This will test:
- ✅ Syntax validation
- ✅ Command line interface  
- ✅ Code structure verification
- ✅ Configuration validation

## 🎯 Expected Output

### RAG System Output:
```
Processing: 'Night driving with 3 vehicles and headlights'
Finding best scenario match...
Selected: Night time driving scenario with vehicle lights
Generating reliable CARLA code...
Syntax validation: PASSED
Code saved to: ../generated_scenarios/reliable_night-driving_1754451658.py

SUCCESS: Reliable code generated!
```

### Generated Script Output:
```
Starting CARLA Scenario: Night time driving scenario with vehicle lights
Connecting to CARLA at 127.0.0.1:2000...
Connected to CARLA 0.9.15
Setting up night weather...
Spawning 3 vehicles...
  Vehicle 1 spawned: vehicle.tesla.model3
  Vehicle 2 spawned: vehicle.bmw.grandtourer  
  Vehicle 3 spawned: vehicle.audi.tt
Camera attached successfully
Running simulation for 30 seconds...
  Saved 30 frames...
  Saved 60 frames...
Simulation completed after 30.1 seconds
Total frames saved: 901
```

## 🚀 Production Usage

1. **Dataset Creation**: Generate diverse driving scenarios for ML training
2. **Scenario Testing**: Validate autonomous driving algorithms  
3. **Research**: Study vehicle behavior in different conditions
4. **Simulation**: Create realistic traffic scenarios

## �🛠️ Troubleshooting

### Common Issues:

**"Failed to connect to CARLA"**
- Start CARLA server: `CarlaUE4.exe`
- Check port 2000 is available
- Verify CARLA is running on localhost:2000

**"Syntax validation failed"**
- Use `reliable_template_rag.py` (template-based)
- Avoid `simple_carla_rag_demo.py` for production

**"No frames saved"**
- Check output directory permissions
- Verify CARLA version compatibility
- Ensure camera attachment succeeded

**"Import errors in RAG system"**
- Activate virtual environment: `venv_langchain\Scripts\activate`
- Check API key in `.env` file

## 📊 Performance

- **Scenario Matching**: ~2 seconds
- **Code Generation**: ~5-10 seconds  
- **Syntax Validation**: Instant
- **Frame Generation**: ~30 FPS (CARLA dependent)

## 🔮 Future Enhancements

- [ ] Custom weather parameter fine-tuning
- [ ] Multi-camera angle support
- [ ] Vehicle behavior customization
- [ ] Real-time scenario editing
- [ ] Advanced traffic light scenarios

---

**Ready to generate unlimited CARLA scenarios with AI! 🚗🤖**

4. **Import errors in generated scripts**
   - Use Python 3.8 for running CARLA scripts
   - Install required packages: `pip install carla numpy opencv-python`

### Testing Commands

```powershell
# Test RAG setup
python test_rag_setup.py

# Test single request
python test_single_request.py

# Run interactive demo
python simple_carla_rag_demo.py
```

## 📝 Example Usage

```python
from simple_carla_rag_demo import SimpleCarlaRAG

# Initialize RAG system
rag = SimpleCarlaRAG("../carla_scenarios_db.json")

# Process request
result = rag.process_request("3 cars driving at night with headlights")

# Show explanation
print(result['explanation'])

# Save generated code
save_code_to_file(result['code'], "night_driving.py")
```

## 🎯 Next Steps

1. **Vector Database**: Upgrade to ChromaDB for better semantic search
2. **More Scenarios**: Expand the scenario database
3. **Real-time Editing**: Implement live scenario modification
4. **Performance Metrics**: Add simulation performance tracking
5. **Web Interface**: Create a web UI for easier interaction

---

**Generated by CARLA RAG Pipeline - Simple Explainable RAG for Autonomous Driving Scenarios**
