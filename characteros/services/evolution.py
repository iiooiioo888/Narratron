"""CharacterOS 演化引擎：Profile + 演化參數 → evolved_manifest。"""

from typing import Dict, Any, Optional
import copy


class EvolutionEngine:
    """
    演化引擎：將基礎 Profile + 演化參數 → 演化後的 Manifest
    
    當前支援的演化維度：
    - 年齡變化（age_override）→ 皺紋、白髮、體型變化
    - 情緒狀態（emotion_state）→ AU（Action Units）強度調整
    - 場景上下文（scene_context）→ 傷痕、服裝破損
    - 天氣環境（weather）→ 濕髮、霧氣、日照
    - 受傷程度（injury_level）→ 可見傷痕、血漬
    - 身體變化（body_modification）→ 肌肉量、身高微調
    """
    
    # 年齡映射表（視覺年齡 → 描述詞）
    AGE_VISUAL_MAP = {
        (0, 12): "child",
        (13, 19): "teenager",
        (20, 35): "young_adult",
        (36, 50): "middle_aged",
        (51, 70): "senior",
        (71, 150): "elderly"
    }
    
    # 情緒映射表（emotion → AU 強度 + 生圖描述）
    EMOTION_AU_MAP = {
        "neutral": {"au_intensity": 0.1, "micro_expressions": ["relaxed"], "prompt": "neutral expression, relaxed face"},
        "happy": {"au_intensity": 0.6, "micro_expressions": ["smile_corners", "crow_feet"], "prompt": "happy expression, genuine smile, lifted cheeks"},
        "sad": {"au_intensity": 0.4, "micro_expressions": ["downturned_mouth", "inner_brow_raise"], "prompt": "sad expression, downturned mouth, melancholic eyes"},
        "angry": {"au_intensity": 0.8, "micro_expressions": ["furrowed_brow", "tightened_lips"], "prompt": "angry expression, furrowed brow, tightened lips"},
        "fearful": {"au_intensity": 0.7, "micro_expressions": ["wide_eyes", "raised_brows"], "prompt": "fearful expression, wide eyes, raised brows"},
        "determined": {"au_intensity": 0.5, "micro_expressions": ["focused_gaze", "slight_frown"], "prompt": "determined expression, focused gaze, slight frown"},
    }
    
    # 場景映射表（scene → 環境效果 + 生圖描述）
    SCENE_EFFECTS_MAP = {
        "battle": {"injury_chance": 0.8, "dirt_level": 0.6, "outfit_damage": "moderate", "prompt": "battle aftermath, dirt smudges, damaged clothing, combat wear"},
        "formal_event": {"injury_chance": 0.0, "dirt_level": 0.0, "outfit_damage": "none", "prompt": "formal event attire, clean presentation, ceremonial setting"},
        "casual_street": {"injury_chance": 0.1, "dirt_level": 0.2, "outfit_damage": "light_wear", "prompt": "casual street environment, everyday wear, urban setting"},
        "post_apocalyptic": {"injury_chance": 0.6, "dirt_level": 0.8, "outfit_damage": "heavy", "prompt": "post-apocalyptic wear, heavy dirt, frayed clothing, survival wear"},
    }

    WEATHER_EFFECTS_MAP = {
        "clear": {"lighting": "clear daylight", "surface": "dry", "prompt": "clear weather, natural daylight"},
        "rain": {"lighting": "overcast wet", "surface": "wet", "prompt": "rain, wet hair, rain droplets, overcast lighting"},
        "snow": {"lighting": "cold diffuse", "surface": "frost", "prompt": "snow, cold breath, winter atmosphere"},
        "fog": {"lighting": "soft diffused", "surface": "damp", "prompt": "fog, mist, low visibility, soft diffused light"},
        "night": {"lighting": "night ambient", "surface": "dry", "prompt": "night time, dim ambient light, nocturnal mood"},
        "storm": {"lighting": "dramatic storm", "surface": "wet", "prompt": "storm, strong wind, dramatic sky"},
    }
    
    def apply_evolution(
        self,
        base_manifest: Dict[str, Any],
        evolution_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        應用演化規則到基礎 Manifest
        
        Args:
            base_manifest: 原始 Profile Manifest
            evolution_params: 演化參數（age, emotion, scene, injury, modifications）
        
        Returns:
            evolved_manifest: 演化後的完整 Manifest
        """
        # 深度拷貝以避免修改原始數據
        evolved = copy.deepcopy(base_manifest)
        
        # 1. 應用年齡變化
        if 'age_override' in evolution_params and evolution_params['age_override']:
            evolved = self._apply_age_evolution(evolved, evolution_params['age_override'])
        
        # 2. 應用情緒變化
        if 'emotion_state' in evolution_params and evolution_params['emotion_state']:
            evolved = self._apply_emotion_evolution(evolved, evolution_params['emotion_state'])
        
        # 3. 應用場景效果
        if 'scene_context' in evolution_params and evolution_params['scene_context']:
            evolved = self._apply_scene_evolution(evolved, evolution_params['scene_context'])

        # 4. 應用天氣環境
        if evolution_params.get('weather'):
            evolved = self._apply_weather_evolution(evolved, evolution_params['weather'])
        
        # 5. 應用受傷程度
        if 'injury_level' in evolution_params and evolution_params['injury_level'] > 0:
            evolved = self._apply_injury_evolution(evolved, evolution_params['injury_level'])
        
        # 6. 應用身體變化
        if 'body_modification' in evolution_params and evolution_params['body_modification']:
            evolved = self._apply_body_modification(evolved, evolution_params['body_modification'])
        
        # 7. 應用自訂參數（直接合併）
        if 'custom_params' in evolution_params and evolution_params['custom_params']:
            evolved = self._merge_custom_params(evolved, evolution_params['custom_params'])
        
        return evolved
    
    def _apply_age_evolution(self, manifest: Dict[str, Any], target_age: int) -> Dict[str, Any]:
        """應用年齡演化"""
        # 更新視覺年齡
        if '_identity' in manifest:
            manifest['_identity']['age_visual'] = target_age
            manifest['_identity']['age_appearance'] = f"{target_age} years old"
            blend = manifest['_identity'].setdefault('blend', {})
            if isinstance(blend, dict):
                blend['age_visual'] = target_age
            
            # 根據年齡區間添加描述詞
            age_category = None
            for (min_age, max_age), category in self.AGE_VISUAL_MAP.items():
                if min_age <= target_age <= max_age:
                    age_category = category
                    break
            
            if age_category:
                # 添加到 style 的描述中
                if '_style' not in manifest:
                    manifest['_style'] = {}
                
                age_descriptors = {
                    "child": "youthful features, smooth skin, innocent expression",
                    "teenager": "developing features, clear skin, energetic vibe",
                    "young_adult": "mature features, defined bone structure, confident presence",
                    "middle_aged": "subtle laugh lines, experienced gaze, distinguished look",
                    "senior": "visible wrinkles, silver hair hints, wise expression",
                    "elderly": "deep wrinkles, weathered skin, dignified posture"
                }
                
                if 'additional_descriptors' not in manifest['_style']:
                    manifest['_style']['additional_descriptors'] = []
                
                manifest['_style']['additional_descriptors'].append(age_descriptors[age_category])
        
        return manifest
    
    def _append_descriptor(self, manifest: Dict[str, Any], text: str) -> None:
        cleaned = str(text or "").strip()
        if not cleaned:
            return
        style = manifest.setdefault("_style", {})
        descriptors = style.setdefault("additional_descriptors", [])
        if isinstance(descriptors, list) and cleaned not in descriptors:
            descriptors.append(cleaned)

    def _apply_emotion_evolution(self, manifest: Dict[str, Any], emotion: str) -> Dict[str, Any]:
        """應用情緒演化"""
        key = str(emotion or "").strip().lower()
        emotion_data = self.EMOTION_AU_MAP.get(key, self.EMOTION_AU_MAP["neutral"])
        
        if '_expression' in manifest:
            manifest['_expression']['base_emotion'] = key or emotion
            manifest['_expression']['au_intensity'] = emotion_data['au_intensity']
            manifest['_expression']['micro_expressions'] = emotion_data['micro_expressions']
        else:
            manifest['_expression'] = {
                'base_emotion': key or emotion,
                'au_intensity': emotion_data['au_intensity'],
                'micro_expressions': emotion_data['micro_expressions']
            }
        if emotion_data.get("prompt"):
            self._append_descriptor(manifest, str(emotion_data["prompt"]))
        
        return manifest
    
    def _apply_scene_evolution(self, manifest: Dict[str, Any], scene: str) -> Dict[str, Any]:
        """應用場景演化"""
        key = str(scene or "").strip().lower()
        scene_data = self.SCENE_EFFECTS_MAP.get(key, {
            "injury_chance": 0.1,
            "dirt_level": 0.1,
            "outfit_damage": "none",
            "prompt": key or scene,
        })
        
        # 添加到 manifest 的 scene_context
        manifest['_scene_context'] = {
            'scene_type': key or scene,
            'environmental_effects': scene_data
        }
        if scene_data.get("prompt"):
            self._append_descriptor(manifest, str(scene_data["prompt"]))
        
        return manifest

    def _apply_weather_evolution(self, manifest: Dict[str, Any], weather: str) -> Dict[str, Any]:
        """應用天氣演化。"""
        key = str(weather or "").strip().lower()
        weather_data = self.WEATHER_EFFECTS_MAP.get(key, {
            "lighting": key or "unspecified",
            "surface": "dry",
            "prompt": key,
        })
        manifest["_weather"] = {
            "condition": key or str(weather or "").strip(),
            "effects": weather_data,
        }
        if weather_data.get("prompt"):
            self._append_descriptor(manifest, str(weather_data["prompt"]))
        return manifest
    
    def _apply_injury_evolution(self, manifest: Dict[str, Any], injury_level: float) -> Dict[str, Any]:
        """應用受傷演化"""
        injury_level = max(0.0, min(1.0, injury_level))  # 限制在 0-1 範圍
        
        # 生成傷痕描述
        injury_descriptions = []
        if injury_level > 0.3:
            injury_descriptions.append("minor_scrapes")
        if injury_level > 0.5:
            injury_descriptions.append("visible_bruises")
        if injury_level > 0.7:
            injury_descriptions.append("blood_stains")
        if injury_level > 0.9:
            injury_descriptions.append("deep_wounds")
        
        if '_body' not in manifest:
            manifest['_body'] = {}
        
        manifest['_body']['injury_marks'] = injury_descriptions
        manifest['_body']['injury_intensity'] = injury_level
        if injury_descriptions:
            readable = ", ".join(item.replace("_", " ") for item in injury_descriptions)
            self._append_descriptor(manifest, f"visible injuries: {readable}")
        
        return manifest
    
    def _apply_body_modification(
        self,
        manifest: Dict[str, Any],
        modifications: Dict[str, Any]
    ) -> Dict[str, Any]:
        """應用身體變化"""
        if '_body' not in manifest:
            manifest['_body'] = {}
        
        # 合併修改
        for key, value in modifications.items():
            manifest['_body'][key] = value
        
        return manifest
    
    def _merge_custom_params(
        self,
        manifest: Dict[str, Any],
        custom_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """合併自訂參數"""
        # 直接合併到頂層（避免覆蓋保留鍵）
        reserved_keys = ['_identity', '_style', '_expression', '_body', '_scene_context', '_weather']
        
        for key, value in custom_params.items():
            if key not in reserved_keys:
                manifest[key] = value
        
        return manifest


# 測試用
if __name__ == "__main__":
    engine = EvolutionEngine()
    
    # 測試基礎 manifest
    base_manifest = {
        "_identity": {
            "name": "林默",
            "age_visual": 28,
            "gender_spectrum": 0.6
        },
        "_style": {
            "outfit": {
                "description": "tactical jacket"
            }
        },
        "_expression": {
            "base_emotion": "neutral",
            "au_intensity": 0.1
        },
        "_body": {
            "height_cm": 178,
            "build": "athletic"
        }
    }
    
    # 測試演化參數
    params = {
        "age_override": 80,
        "emotion_state": "angry",
        "scene_context": "battle",
        "injury_level": 0.6
    }
    
    evolved = engine.apply_evolution(base_manifest, params)
    
    print("Evolved Manifest:")
    import json
    print(json.dumps(evolved, indent=2, ensure_ascii=False))
