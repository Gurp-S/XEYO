import {createRoot} from 'react-dom/client';
import {PetApp} from '@/pet/PetApp';
import '@/pet/pet.css';

document.body.classList.add('xeyo-pet-window');

const container = document.getElementById('pet-root');
if (container) {
  createRoot(container).render(<PetApp />);
}
