"""Domain-specific regex patterns for structured extraction.

Each domain maps field names to a list of compiled-ready regex patterns.
The patterns capture the relevant entity so callers can use match.group(0).
"""

from __future__ import annotations

DOMAIN_PATTERNS: dict[str, dict[str, list[str]]] = {
    "cv_movement": {
        "disease": [
            r"(?i)\b(spinocerebellar ataxia|SCA[\s-]?\d+|parkinson(?:'s)?\s*disease|PD\b"
            r"|multiple system atrophy|MSA\b|huntington(?:'s)?\s*disease"
            r"|dystonia|essential tremor|cerebellar ataxia"
            r"|friedreich(?:'s)?\s*ataxia|ataxia telangiectasia"
            r"|multiple sclerosis|amyotrophic lateral sclerosis|ALS\b)\b",
        ],
        "cv_tool": [
            r"(?i)\b(mediapipe|openpose|open\s*pose|kinect|azure\s*kinect|vicon"
            r"|leap\s*motion|blazepose|movenet|alphapose|hrnet|detectron2?"
            r"|optitrack|qualisys|xsens|IMU)\b",
        ],
        "ml_model": [
            r"(?i)\b(random\s*forest|support\s*vector\s*(?:machine|regressor)|SVM\b|SVR\b"
            r"|CNN\b|LSTM\b|BiLSTM|convolutional\s*neural\s*network"
            r"|recurrent\s*neural\s*network|transformer|XGBoost"
            r"|gradient\s*boosting|logistic\s*regression"
            r"|k-?nearest\s*neighbor|KNN\b|decision\s*tree"
            r"|deep\s*learning|neural\s*network"
            r"|ResNet|VGG|YOLO|attention\s*mechanism|GRU\b"
            r"|autoencoder|variational\s*autoencoder|GAN\b)\b",
        ],
        "motor_task": [
            r"(?i)\b(gait\s*analysis|gait|walking|finger\s*tapping|toe\s*tapping"
            r"|heel[\s-]?knee[\s-]?shin|rapid\s*alternating"
            r"|pronation[\s-]?supination|postur(?:al|e)\s*(?:sway|stability|control)?"
            r"|balance|standing|tremor\s*(?:analysis|assessment)?"
            r"|hand\s*movement|upper\s*limb|lower\s*limb"
            r"|arm\s*swing|sit[\s-]?to[\s-]?stand|tandem\s*(?:gait|walk)"
            r"|reach(?:ing)?|grasp(?:ing)?|diadochokinesis)\b",
        ],
        "clinical_scale": [
            r"(?i)\b(SARA\b|ICARS\b|UPDRS\b|MDS[\s-]?UPDRS"
            r"|Berg\s*Balance\s*Scale|Tinetti|TUG\b|Timed\s*Up\s*and\s*Go"
            r"|6[\s-]?(?:minute|min)\s*walk\s*test|functional\s*reach"
            r"|Barthel|modified\s*Rankin|EDSS\b|Ashworth|ARAT\b)\b",
        ],
        "metric": [
            r"(?i)\b(accuracy|precision|recall|F1[\s-]?score|AUC\b|ROC\b"
            r"|sensitivity|specificity|correlation|Pearson|Spearman|ICC\b"
            r"|RMSE\b|MAE\b|mean\s*(?:squared|absolute)\s*error"
            r"|R[\s\u00b2]|r\u00b2|coefficient\s*of\s*determination"
            r"|p[\s-]?value|confidence\s*interval|CI\b)\b",
        ],
        "sample_size": [
            r"(?i)(?:n\s*=\s*(\d+))",
            r"(?i)(\d+)\s*(?:participants|patients|subjects|individuals|controls|healthy)",
        ],
        "validation": [
            r"(?i)\b(\d+[\s-]?fold\s*cross[\s-]?validation|leave[\s-]?one[\s-]?(?:subject[\s-]?)?out"
            r"|LOSO\b|LOOCV\b|train[\s/]test\s*split|hold[\s-]?out"
            r"|bootstrapping|nested\s*cross[\s-]?validation|stratified)\b",
        ],
    },
    "biomedical_general": {
        "intervention": [
            r"(?i)\b(treatment|therapy|drug|medication|intervention"
            r"|placebo|randomized|RCT\b|clinical\s*trial)\b",
        ],
        "outcome": [
            r"(?i)\b(primary\s*outcome|secondary\s*outcome|endpoint"
            r"|mortality|survival|efficacy|adverse\s*event|side\s*effect)\b",
        ],
        "sample_size": [
            r"(?i)(?:n\s*=\s*(\d+))",
            r"(?i)(\d+)\s*(?:participants|patients|subjects)",
        ],
    },
}


# Keyword morphological variants for expanded search.
# Maps a base keyword to additional forms that should also be matched.
KEYWORD_VARIANTS: dict[str, list[str]] = {
    "ataxia": ["ataxic", "ataxias", "atactic"],
    "kinematic": ["kinematics", "kinematical", "kinematically"],
    "gait": ["walking", "ambulation", "locomotion"],
    "tremor": ["tremors", "tremulous"],
    "pose estimation": ["pose detection", "body tracking", "skeleton tracking"],
    "machine learning": ["ML", "artificial intelligence", "AI"],
    "deep learning": ["DL", "neural network", "neural networks"],
    "mediapipe": ["media pipe", "BlazePose"],
    "classification": ["classifier", "classifying", "classify"],
    "regression": ["regressor", "regressing"],
    "parkinson": ["parkinsonian", "parkinsonism"],
    "cerebellar": ["cerebellum"],
    "upper limb": ["upper extremity", "upper extremities"],
    "lower limb": ["lower extremity", "lower extremities"],
}
