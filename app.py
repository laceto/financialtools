# streamlit run app.py
# app.py
# import streamlit as st
# # import rich
# from financialtools.chains import get_stock_evaluation_report

# # Title
# st.title("String Echo App")

# # Input box
# user_input = st.text_input("Enter a string:")

# # report = 

# # Output
# if user_input:
#     st.write("You entered:")
#     st.success(st.json(get_stock_evaluation_report(user_input)))


# app.py
# Run with: streamlit run app.py

import streamlit as st
from financialtools.chains import get_stock_evaluation_report

# --- Page Config ---
st.set_page_config(
    page_title="Trading Assistant",
    page_icon="📈",
    layout="centered",
    initial_sidebar_state="expanded"
)

# --- Sidebar ---
with st.sidebar:
    st.image("https://img.icons8.com/color/96/stock-share.png", width=100)
    st.title("📈 Trading Assistant")
    st.markdown("Your AI-powered stock evaluation helper.")
    st.markdown("---")
    st.write("⚡ **Features**")
    st.write("- Get instant stock evaluations")
    st.write("- AI-driven insights")
    st.write("- Designed for traders")
    st.markdown("---")
    st.info("💡 Tip: Enter a stock ticker or company name!")

# --- Main Title ---
st.title("📊 AI Stock Evaluation")
st.markdown("Enter a stock ticker or company name below to generate an AI-powered evaluation report.")

# --- User Input ---
user_input = st.text_input(
    "🔍 Search for a stock",
    placeholder="e.g., AAPL, MSFT, TSLA",
    help="Type a stock ticker or company name to get its evaluation."
)

# --- Process Input ---
if user_input:
    with st.spinner(f"Fetching AI report for **{user_input}**..."):
        try:
            report = get_stock_evaluation_report(user_input)
            
            st.subheader(f"📄 Stock Evaluation for `{user_input.upper()}`")
            st.success("✅ Report generated successfully!")

            # Display JSON in a collapsible section
            st.json(report, expanded=False)
            
        except Exception as e:
            st.error(f"❌ Could not fetch report: {e}")
else:
    st.warning("👆 Please enter a stock ticker or company name.")

# --- Footer ---
st.markdown("---")
st.caption("⚡ Powered by AI • Built with Streamlit")
