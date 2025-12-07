using System;
using UnityEngine;
using NineSolTrainerApp;

namespace NineSolTrainer
{
    public class Loader
    {
        private static readonly GameObject MGameObject = new GameObject();

        public static void Load()
        {
            MGameObject.AddComponent<NineSolTrainerMain>();
            UnityEngine.Object.DontDestroyOnLoad(MGameObject);
        }

        public static void Unload()
        {
            UnityEngine.Object.Destroy(MGameObject);
        }
    }
}