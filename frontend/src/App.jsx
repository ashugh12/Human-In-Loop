import { useEffect, useState } from 'react';
import { db } from './firebase';
import './styles.css';

export default function App() {
  const [requests, setRequests] = useState([]);

  useEffect(() => {
    const unsubscribe = db.collection("help_requests").onSnapshot((snapshot) => {
      const data = snapshot.docs.map((doc) => ({ id: doc.id, ...doc.data() }));
      setRequests(data.sort((a, b) => b.created_at.localeCompare(a.created_at)));
    });
    return () => unsubscribe();
  }, []);

  const handleResolve = (id, answer) => {
    if (!answer.trim()) return;
    db.collection("help_requests").doc(id).update({
      status: "resolved",
      answer,
      resolved_at: new Date().toISOString(),
    });
  };

  return (
    <div className="container">
      <h1>💬 Luxe Glow Salon — Supervisor Dashboard</h1>

      {requests.length === 0 && <p className="empty">No help requests yet 🎉</p>}

      <div className="request-list">
        {requests.map((r) => (
          <div
            key={r.id}
            className={`request-card ${r.status === "resolved" ? "resolved" : ""}`}
          >
            <p className="question">
              ❓ <strong>{r.clarified_question || r.question}</strong>
            </p>

            <p className="status">
              Status:{' '}
              <strong
                style={{
                  color: r.status === "resolved" ? "#2e7d32" : "#d17b00",
                }}
              >
                {r.status}
              </strong>
            </p>

            {r.status === "pending" && (
              <input
                type="text"
                className="answer-input"
                placeholder="Type supervisor answer and press Enter..."
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    handleResolve(r.id, e.target.value);
                    e.target.value = "";
                  }
                }}
              />
            )}

            {r.status === "resolved" && (
              <p className="answer">✅ {r.answer}</p>
            )}

            <p className="time">
              Created: {new Date(r.created_at).toLocaleString()}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
