import os
import time
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, session, send_file
from flask_session import Session
from mongo import responses_collection  # Now using the unified collection
from bson import ObjectId  # For converting session ID to ObjectId

app = Flask(__name__)
app.secret_key = "your_secret_key"  # Replace with a secure key for production

# Configure server-side sessions (using the filesystem)
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = "./flask_session_dir"
app.config["SESSION_PERMANENT"] = False
Session(app)

UPLOAD_FOLDER = "uploads"
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def generate_unique_filename(original_filename):
    timestamp = int(time.time())
    name, ext = os.path.splitext(original_filename)
    unique_filename = f"{name}_{timestamp}{ext}"
    return unique_filename

def save_excel(dataframe, file_id, output_filename="Rated.xlsx"):
    save_path = os.path.join(UPLOAD_FOLDER, f"{os.path.splitext(file_id)[0]}_{output_filename}")
    dataframe.to_excel(save_path, index=False)
    session["files"][file_id]["saved_file"] = save_path
    print("File saved at:", save_path)

def ensure_files_dict():
    if "files" not in session:
        session["files"] = {}

@app.route("/")
def home():
    return redirect(url_for("register"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        registration_data = {
            "lawyer_name": request.form.get("lawyer_name"),
            "email": request.form.get("email"),
            "graduation_year": request.form.get("graduation_year"),
            "age": request.form.get("age"),
            "gender": request.form.get("gender"),
            "highest_education": request.form.get("highest_education"),
            "use_llms": request.form.get("use_llms"),
            "incorrect_example": request.form.get("incorrect_example"),
            "applied_llms": request.form.get("applied_llms"),
            "difficult_case": request.form.get("difficult_case"),
            # "difficult_case_other": request.form.get("difficult_case_other"),
            "llm_usage": request.form.get("llm_usage")
        }
        
        # Insert a new document containing registration data and save its _id in the session
        if responses_collection is not None:
            result = responses_collection.insert_one({"registration": registration_data})
            session["response_id"] = str(result.inserted_id)
            print("Registration info saved to MongoDB:", registration_data)
        else:
            print("Registration info received (MongoDB not configured):", registration_data)
        
        return redirect(url_for("feedback"))
    return render_template("register.html")

@app.route("/feedback", methods=["GET", "POST"])
def feedback():
    if request.method == "POST":
        feedback_data = {
            "usage_coursework": request.form.get("usage_coursework"),
            "usage_activities": request.form.get("usage_activities"),
            "comprehensibility": request.form.get("comprehensibility"),
            "fluency_english": request.form.get("fluency_english"),
            "coverage": request.form.get("coverage"),
            "relevance_accuracy": request.form.get("relevance_accuracy"),
            "query_completion": request.form.get("query_completion"),
            "proactiveness": request.form.get("proactiveness"),
            "ethical_compliance": request.form.get("ethical_compliance"),
            "multilingual_capacity": request.form.get("multilingual_capacity")
        }
        # Update the existing document with feedback data
        if responses_collection is not None and "response_id" in session:
            responses_collection.update_one(
                {"_id": ObjectId(session["response_id"])},
                {"$set": {"feedback": feedback_data}}
            )
            print("Feedback saved to MongoDB:", feedback_data)
        else:
            print("Feedback received (MongoDB not configured):", feedback_data)
        
        return redirect(url_for("upload"))
    return render_template("feedback.html")

@app.route("/upload", methods=["GET", "POST"])
def upload():
    ensure_files_dict()
    if request.method == "POST":
        file = request.files.get("file")
        if file:
            unique_filename = generate_unique_filename(file.filename)
            filepath = os.path.join(UPLOAD_FOLDER, unique_filename)
            file.save(filepath)
            # Save file details in session keyed by unique filename
            session["files"][unique_filename] = {"file_path": filepath}
            # Read file columns and store them
            df = pd.read_excel(filepath)
            session["files"][unique_filename]["columns"] = df.columns.tolist()
            print("Uploaded file columns:", session["files"][unique_filename]["columns"])
            # Redirect to select_columns route with file id as query parameter
            return redirect(url_for("select_columns", file=unique_filename))
    return render_template("upload.html")

@app.route("/select_columns", methods=["GET", "POST"])
def select_columns():
    file_id = request.args.get("file")
    if not file_id or file_id not in session.get("files", {}):
        return redirect(url_for("upload"))
    
    file_details = session["files"][file_id]
    all_columns = file_details.get("columns", [])
    # Now:
    # Query Column: second column (index 1)
    # Response Column: third column (index 2)
    # Type Column: fourth column (index 3)
    # Rating candidates: from fifth column onward (index 4+)
    rating_candidates = all_columns[4:] if len(all_columns) > 4 else []
    
    if request.method == "POST":
        # Get the mapping from the form
        query_col = request.form.get("query_column")
        response_col = request.form.get("response_column")
        type_col = request.form.get("type_column")
        rating_columns = request.form.getlist("rating_columns")
        
        file_details["rating_columns"] = rating_columns
        
        # Build groups from the Excel file.
        # Group rows by the unique query value (assumes each row has the query already).
        df = pd.read_excel(file_details["file_path"])
        groups_dict = {}
        groups_order = []
        for i, row in df.iterrows():
            raw_query = row.get(query_col, "")
            query_val = raw_query if (pd.notna(raw_query) and str(raw_query).strip()) else None
            response_val = row.get(response_col, "")
            response_val = response_val if (pd.notna(response_val) and str(response_val).strip()) else None
            response_type_val = row.get(type_col, "")
            if query_val is None:
                continue
            if query_val not in groups_dict:
                groups_dict[query_val] = {"query": query_val, "responses": []}
                groups_order.append(query_val)
            if response_val is not None:
                groups_dict[query_val]["responses"].append({
                    "row_index": i,
                    "response": response_val,
                    "response_type": response_type_val
                })
        groups = [groups_dict[q] for q in groups_order]
        file_details["groups"] = groups
        # Initialize navigation indices.
        file_details["current_group_idx"] = 0
        file_details["current_response_idx"] = 0
        # Initialize ratings: a parallel structure (list of groups with one dict per response).
        ratings = []
        for group in groups:
            ratings.append([{} for _ in group["responses"]])
        file_details["ratings"] = ratings
        
        session.modified = True
        
        return redirect(url_for("rate", file=file_id,
                                query_col=query_col,
                                response_col=response_col,
                                type_col=type_col))
    
    return render_template("select_columns.html",
                           all_columns=all_columns,
                           rating_candidates=rating_candidates)


@app.route("/rate", methods=["GET", "POST"])
def rate():
    file_id = request.args.get("file") or request.form.get("file")
    if not file_id or file_id not in session.get("files", {}):
        return redirect(url_for("upload"))
    
    file_details = session["files"][file_id]
    filepath = file_details.get("file_path")
    if not filepath or not os.path.exists(filepath):
        return "File not found. <a href='/upload'>Upload again</a>"
    
    # Get column mappings from GET or POST
    if request.method == "POST":
        query_col = request.form.get("query_col")
        response_col = request.form.get("response_col")
        type_col = request.form.get("type_col")
    else:
        query_col = request.args.get("query_col")
        response_col = request.args.get("response_col")
        type_col = request.args.get("type_col")
    
    groups = file_details.get("groups", [])
    if not groups:
        return "No groups found. <a href='/upload'>Upload again</a>"
    
    total_groups = len(groups)
    current_group_idx = file_details.get("current_group_idx", 0)
    current_group = groups[current_group_idx]
    total_responses = len(current_group.get("responses", []))
    
    if request.method == "POST":
        action = request.form.get("action")
        # Save ratings for all responses in the current group
        ratings = file_details.get("ratings", [])
        current_group_ratings = ratings[current_group_idx]
        for i in range(total_responses):
            current_rating = {}
            for col in file_details.get("rating_columns", []):
                current_rating[col] = request.form.get(f"{col}_{i}")
            current_rating["response_review"] = request.form.get(f"response_review_{i}")
            current_group_ratings[i] = current_rating
        ratings[current_group_idx] = current_group_ratings
        file_details["ratings"] = ratings
        
        # Navigation: change current_group_idx
        if action == "prev":
            if current_group_idx > 0:
                current_group_idx -= 1
        elif action == "next":
            if current_group_idx < total_groups - 1:
                current_group_idx += 1
            else:
                # If on the last group, merge ratings with original DataFrame and save file.
                df = pd.read_excel(filepath)
                ratings_dict = {}
                for g_idx, group in enumerate(groups):
                    for r_idx, resp in enumerate(group["responses"]):
                        row_index = resp["row_index"]
                        ratings_dict[row_index] = file_details["ratings"][g_idx][r_idx]
                for col in file_details.get("rating_columns", []):
                    df[col] = df.index.map(lambda i: ratings_dict.get(i, {}).get(col))
                df["response_review"] = df.index.map(lambda i: ratings_dict.get(i, {}).get("response_review"))
                save_excel(df, file_id)
                return redirect(url_for("download_page", file=file_id))
        
        file_details["current_group_idx"] = current_group_idx
        session.modified = True
        return redirect(url_for("rate", file=file_id,
                                query_col=query_col,
                                response_col=response_col,
                                type_col=type_col))
    
    # Prepare current ratings for the current group if available
    ratings = file_details.get("ratings", [])
    current_rating = ratings[current_group_idx] if ratings and len(ratings) > current_group_idx else [{} for _ in range(total_responses)]
    
    return render_template("rate.html",
                           current_query=current_group["query"],
                           current_group=current_group,
                           current_group_idx=current_group_idx,
                           total_groups=total_groups,
                           total_responses=total_responses,
                           rating_columns=file_details.get("rating_columns", []),
                           query_col=query_col,
                           response_col=response_col,
                           type_col=type_col,
                           file_id=file_id,
                           current_rating=current_rating)

@app.route("/download_page", methods=["GET", "POST"])
def download_page():
    file_id = request.args.get("file")
    if not file_id or file_id not in session.get("files", {}):
        return "No file available for download. <a href='/upload'>Upload again</a>"
    
    saved_file = session["files"][file_id].get("saved_file")
    if not saved_file or not os.path.exists(saved_file):
        return "No file available for download. <a href='/upload'>Upload again</a>"
    
    comment_submitted = False
    if request.method == "POST":
        comment = request.form.get("comment")
        # Update the same document with the general comment
        if comment and responses_collection is not None and "response_id" in session:
            responses_collection.update_one(
                {"_id": ObjectId(session["response_id"])},
                {"$set": {"general_comment": comment}}
            )
            comment_submitted = True
    
    return render_template("download.html", file_id=file_id, comment_submitted=comment_submitted)

@app.route("/download")
def download():
    file_id = request.args.get("file")
    if (file_id and file_id in session.get("files", {}) and 
        "saved_file" in session["files"][file_id] and 
        os.path.exists(session["files"][file_id]["saved_file"])):
        return send_file(session["files"][file_id]["saved_file"], as_attachment=True)
    return "File not found. <a href='/upload'>Upload again</a>"

@app.route("/starter_queries")
def starter_queries():
    return render_template("starter_queries.html")


if __name__ == "__main__":
    app.run(debug=True)