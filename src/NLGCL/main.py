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

def run_single_model(args):
    # configurations initialization
    config = Config(
        model=args.model,
        dataset=args.dataset,
        config_file_list=args.config_file_list
    )
    try:
        assert config["enable_sparse"] in [True, False, None]
    except AssertionError:
        raise ValueError("Your config `enable_sparse` must be `True` or `False` or `None`")
    init_seed(config['seed'], config['reproducibility'])

    # logger initialization
    init_logger(config)
    logger = getLogger()
    logger.info(config)

    # dataset filtering
    dataset = create_dataset(config)
    logger.info(dataset)

    # dataset splitting
    train_data, valid_data, test_data = data_preparation(config, dataset)

    # model loading and initialization
    model = get_model(config['model'])(config, train_data.dataset).to(config['device'])
    logger.info(model)

    # trainer loading and initialization
    trainer = get_trainer(config['MODEL_TYPE'], config['model'])(config, model)

    # model training
    best_valid_score, best_valid_result = trainer.fit(
        train_data, valid_data, saved=True, show_progress=config['show_progress']
    )

    # model evaluation
    test_result = trainer.evaluate(test_data, load_best_model=True, show_progress=config['show_progress'])

    logger.info(set_color('best valid ', 'yellow') + f': {best_valid_result}')
    logger.info(set_color('test result', 'yellow') + f': {test_result}')


def export_mongo_inter(
    mongo_uri: str,
    db_name: str,
    collection_name: str,
    output_dir: str = "src/NLGCL/dataset/game",
    output_file: str = "game.inter",
    batch_size: int = 500_000,
    overwrite: bool = True
):
    """
    Export d'une collection MongoDB filtrée (users >=50 interactions)
    vers un fichier .inter (TSV) normalisé avec user_id:token / item_id:token.
    Si overwrite=False et le fichier existe, l'export est ignoré.

    Args:
        mongo_uri (str): URI MongoDB
        db_name (str): Nom de la base
        collection_name (str): Nom de la collection
        output_dir (str): Dossier de sortie
        output_file (str): Nom du fichier .inter
        batch_size (int): Nombre de lignes par batch
        overwrite (bool): Supprimer le fichier existant si True, sinon ignorer
    """
    os.makedirs(output_dir, exist_ok=True)
    full_path = os.path.join(output_dir, output_file)

    if os.path.exists(full_path):
        if overwrite:
            os.remove(full_path)
            print(f"⚠️ Fichier existant supprimé : {full_path}")
        else:
            print(f"ℹ️ Fichier déjà existant, export ignoré : {full_path}")
            return

    client = MongoClient(mongo_uri)
    db = client[db_name]
    collection = db[collection_name]

    print("📌 Création du pipeline rapide...")
    pipeline = [
    # 1. Grouper par app_id et compter les interactions par jeu
    {"$group": {"_id": "$app_id", "count": {"$sum": 1}}},
    # 2. Filtrer les jeux qui ont au moins 50 interactions
    {"$match": {"count": {"$gte": 50}}},
    # 3. Joindre avec la collection originale pour récupérer les documents complets (interactions)
    {"$lookup": {
        "from": collection_name,
        "localField": "_id",         # app_id filtré
        "foreignField": "app_id",    # app_id de la collection
        "as": "item_interactions"    # Nouveau tableau d'interactions
    }},
    # 4. Dérouler le tableau d'interactions pour avoir chaque interaction individuellement
    {"$unwind": "$item_interactions"},
    # 5. Grouper par utilisateur (user) à partir des interactions filtrées
    {"$group": {"_id": "$item_interactions.user", "count": {"$sum": 1}, "docs": {"$push": "$item_interactions"}}},
    # 6. Filtrer les utilisateurs qui ont au moins 20 interactions (sur les jeux filtrés)
    {"$match": {"count": {"$gte": 20}}},
    # 7. Dérouler le tableau 'docs' pour obtenir les interactions qui ont passé les deux filtres
    {"$unwind": "$docs"},
    # 8. Nettoyer les documents pour s'assurer que user et app_id existent (même si les filtres précédents le garantissent presque)
    {"$match": {
        "docs.user": {"$ne": None},
        "docs.app_id": {"$ne": None}
    }},
    # 9. Projeter les champs nécessaires pour le fichier .inter
    {"$project": {
        "user": "$docs.user",
        "app_id": "$docs.app_id",
        "_id": 0
    }}
    ]

    cursor = collection.aggregate(pipeline, allowDiskUse=True)
    
    batch = []
    total_rows = 0

    for i, doc in enumerate(cursor, 1):
        batch.append(doc)
        if i % batch_size == 0:
            df_batch = pd.DataFrame(batch)
            df_batch.rename(columns={"user": "user:token", "app_id": "app_id:token"}, inplace=True)
            df_batch.to_csv(full_path, mode='a', sep='\t', index=False, lineterminator='\n',
                            header=(total_rows==0))
            total_rows += len(batch)
            batch = []
            print(f"✅ Exporté {total_rows} lignes...")

    if batch:
        df_batch = pd.DataFrame(batch)
        df_batch.rename(columns={"user": "user:token", "app_id": "app_id:token"}, inplace=True)
        df_batch.to_csv(full_path, mode='a', sep='\t', index=False, lineterminator='\n',
                        header=(total_rows==0))
        total_rows += len(batch)

    print(f"🎉 Export terminé : {total_rows} lignes sauvegardées dans {full_path}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', type=str, default='NLGCL', help='name of models')
    parser.add_argument('--dataset', type=str, default='game',
                        help='The datasets can be:')
    mongo_uri = "mongodb://NebuZard:7YAMTHHD@10.242.216.203:27017"
    print ("config_OK")
    export_mongo_inter(mongo_uri=mongo_uri,db_name="Steam_Project",collection_name="reviews")
    #p = Path("src/NLGCL/dataset/game/game.inter")
    #p.write_text(p.read_bytes().decode("utf-8", "ignore"), encoding="utf-8")
    parser.add_argument('--config_files', type=str, default='', help='External config file name.')
    args, _ = parser.parse_known_args()

    # Config files
    args.config_file_list = [
        'src/NLGCL/properties/overall.yaml'
    ]
    if args.config_files != '':
        args.config_file_list.extend(args.config_files.split(","))
    if args.dataset in ['yelp', 'pinterest', 'QB-video', 'alibaba','game']:
        args.config_file_list.append(f'src/NLGCL/properties/{args.dataset}.yaml')
    
    print("All before_model_ok")

    run_single_model(args)
    