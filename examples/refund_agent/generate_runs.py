import sys
sys.path.insert(0, "packages/python-sdk")

from agent import simulate_agent

def main():
    print("Generating correct run (current policy)...")
    simulate_agent(use_stale_memory=False)
    
    print("Generating faulty run (stale memory)...")
    simulate_agent(use_stale_memory=True)
    
    print("\n✅ Two runs generated successfully!")
    print("Open http://localhost:5173 to inspect them.")
    print("Use the Diff tab to compare and see the stale memory bug.")

if __name__ == "__main__":
    main()