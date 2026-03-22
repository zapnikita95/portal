//
//  Share Extension — появляется в системном «Поделиться» (receive_sharing_intent).
//

import receive_sharing_intent

class ShareViewController: RSIShareViewController {

    override func shouldAutoRedirect() -> Bool {
        // Сразу открываем Portal с выбранными файлами.
        true
    }

    override func presentationAnimationDidFinish() {
        super.presentationAnimationDidFinish()
        navigationController?.navigationBar.topItem?.rightBarButtonItem?.title = "Portal"
    }
}
