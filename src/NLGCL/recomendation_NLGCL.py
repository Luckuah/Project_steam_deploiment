import argparse
import logging
from logging import getLogger
import torch
import os
from recbole.utils import init_logger, init_seed, set_color
from recbole_gnn.config import Config
from recbole_gnn.utils import create_dataset, data_preparation, get_model, get_trainer

import pandas as pd
from pymongo import MongoClient
import boto3

def download_model_from_s3(model_name):
    """Télécharge le modèle depuis S3 vers /tmp s'il n'est pas déjà présent."""
    s3_bucket = os.getenv("S3_BUCKET")
    local_path = f"/tmp/{model_name}"
    
    if not os.path.exists(local_path):
        getLogger().info(f"📥 Téléchargement du modèle {model_name} depuis S3 ({s3_bucket})...")
        s3 = boto3.client('s3')
        # On suppose que ton modèle est dans un dossier 'models/' sur S3
        s3.download_file(s3_bucket, f"models/{model_name}", local_path)
        getLogger().info("✅ Téléchargement terminé.")
    else:
        getLogger().info(f"ℹ️ Modèle {model_name} déjà présent dans /tmp.")
    
    return local_path

def normalize_path(path: str) -> str:
    """
    If running on Linux, convert Windows-style backslashes to forward slashes.
    Otherwise, return the path unchanged.
    """
    if os.name == "posix":  # Linux, macOS, etc.
        return path.replace("\\", "/")
    return path

def recommend_topk(model, dataset, train_data, user_id, topk=30, device='cpu'):
    """
    Retourne le top-k items pour un utilisateur donné.

    Args:
        model: modèle Recbole déjà chargé et en mode eval().
        dataset: dataset Recbole.
        train_data: train_data Recbole.
        user_id: index interne de l'utilisateur.
        topk: nombre d'items à retourner.
        device: 'cpu' ou 'cuda'.

    Returns:
        list: top-k item_ids recommandés.
    """
    # --- Convertir user_id en token string si nécessaire ---
    user_id_str = str(user_id)
    user_idx = dataset.token2id('user', user_id_str)

    logger = getLogger()

    # Tous les items
    all_items = torch.arange(dataset.item_num, device=device)

    # Items déjà vus par l'utilisateur
    inter_feat = train_data.dataset.inter_feat
    user_mask = inter_feat['user'] == user_idx
    seen_items = inter_feat['app_id'][user_mask].tolist()

    # Items candidats
    candidate_items = torch.tensor([i for i in all_items if i.item() not in seen_items], device=device)


    # Calculer les scores
    with torch.no_grad():
        user_emb = model.user_embedding(torch.tensor([user_idx], device=device))
        item_emb = model.item_embedding(candidate_items)
        scores = (user_emb * item_emb).sum(dim=-1)  # produit scalaire


    # Top-k
    topk_scores, topk_indices = torch.topk(scores, min(topk, len(candidate_items)))
    topk_items = [dataset.id2token('app_id', idx.item()) for idx in topk_indices]

    logger.info(set_color(f"Top-{topk} recommandations pour user {dataset.id2token('user', user_idx)}", "green"))
    logger.info(topk_items)

    return topk_items

def setup_recbole_model(model_filename, dataset_name, config_file_list):

    model_filename = "NLGCL-Dec-02-2025_17-09-34.pth"
    # --- NOUVEAU : Récupération depuis S3 ---
    # On passe le nom du fichier (NLGCL-Dec-02-2025_17-09-34.pth)
    # et on récupère le chemin local (/tmp/NLGCL-...)
    model_path = download_model_from_s3(model_filename)

    # --- 1. Charger la config ---
    config = Config(model="NLGCL", dataset=dataset_name, config_file_list=config_file_list)
    # ... (reste de ton code inchangé jusqu'au chargement du checkpoint)


    # --- 2. Suppression du cache pour forcer la recréation du Dataset ---
    dataset_dir = os.path.join(config['data_path'], dataset_name)
    
    cache_files = [f'{dataset_name}.dataset', f'{dataset_name}.pth']
    for filename in cache_files:
        full_path = os.path.join(dataset_dir, filename)
        if os.path.exists(full_path):
            os.remove(full_path)
            getLogger().warning(f"Cache Recbole supprimé : {filename}")


    # --- 3. Charger le dataset (forcé de se recréer) ---
    # Le dataset est maintenant créé avec les dimensions de game.inter (1.1M users)
    dataset = create_dataset(config)
    train_data, _, _ = data_preparation(config, dataset)

    # --- 4. Initialiser le modèle (avec les bonnes dimensions) ---
    model_class = get_model(config['model'])
    model = model_class(config, train_data.dataset).to(config['device'])

    # --- 5. Charger les poids ---
    # On utilise maintenant model_path qui pointe vers /tmp/
    checkpoint = torch.load(model_path, map_location=config['device'], weights_only=False)
        
    if 'state_dict' in checkpoint:
        pretrained_state_dict = checkpoint['state_dict']
        
        # Clés d'embedding à ignorer au cas où une petite différence subsiste
        keys_to_ignore = [
            'user_embedding.weight',
            'item_embedding.weight'
        ]

        # Supprimer les clés du dictionnaire des poids si elles existent
        for key in keys_to_ignore:
            if key in pretrained_state_dict:
                del pretrained_state_dict[key]
                getLogger().warning(f"Clé d'embedding supprimée du checkpoint car taille non correspondante : {key}")
            
        # Chargement partiel des poids (strict=False)
        model.load_state_dict(pretrained_state_dict, strict=False)
        getLogger().info(set_color("Chargement partiel réussi. Le modèle NLGCL est prêt.", "yellow"))

    else:
        raise ValueError("Le checkpoint ne contient pas 'state_dict'.")
        
    model.eval()

    return model, dataset, train_data, config['device']
